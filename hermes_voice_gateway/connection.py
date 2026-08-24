"""State machine одного WebSocket-соединения."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic
from typing import Any

from .protocol import ControlMessage, MessageType, ProtocolError

AUDIO_SEQUENCE_BYTES = 8


class ConnectionState(StrEnum):
    UNPAIRED = "unpaired"
    READY = "ready"
    CLOSED = "closed"


PRE_AUTH_MESSAGES = {
    MessageType.PAIR_REQUEST,
    MessageType.HELLO,
    MessageType.PING,
    MessageType.TEST,
}


@dataclass(slots=True)
class CompletedFile:
    name: str
    mime: str
    data: bytes = field(repr=False)


@dataclass(slots=True)
class PendingFile:
    name: str
    mime: str
    size: int
    data: bytearray = field(default_factory=bytearray, repr=False)


@dataclass(slots=True)
class ConnectionContext:
    state: ConnectionState = ConnectionState.UNPAIRED
    device_id: str | None = None
    user_name: str = ""
    chat_id: str | None = None
    muted: bool = False
    paused: bool = False
    mode: str = "voice_only"
    active_audio_seq: int | None = None
    completed_audio_seq: int | None = None
    pending_file: PendingFile | None = None
    last_seen: float = field(default_factory=monotonic)

    def authorize(self, message: ControlMessage) -> None:
        """Проверяет допустимость типа в текущем auth-состоянии."""

        if self.state is ConnectionState.CLOSED:
            raise ProtocolError("connection_closed", "Соединение уже закрыто")
        if self.state is not ConnectionState.READY and message.type not in PRE_AUTH_MESSAGES:
            raise ProtocolError("pair_required", "Сначала требуется pairing и hello")
        self.last_seen = monotonic()

    def mark_ready(self, *, device_id: str, user_name: str, chat_id: str) -> None:
        if self.state is ConnectionState.CLOSED:
            raise ProtocolError("connection_closed", "Соединение уже закрыто")
        self.device_id = device_id
        self.user_name = user_name
        self.chat_id = chat_id
        self.state = ConnectionState.READY
        self.last_seen = monotonic()

    def start_audio(self, seq: int) -> None:
        if self.state is not ConnectionState.READY:
            raise ProtocolError("pair_required", "Аудио требует авторизации")
        if self.muted or self.paused or self.mode == "off":
            raise ProtocolError("audio_disabled", "Приём аудио отключён")
        if self.active_audio_seq is not None:
            raise ProtocolError("audio_in_progress", "Предыдущая реплика не завершена")
        if self.pending_file is not None:
            raise ProtocolError("file_in_progress", "Сначала завершите передачу файла")
        self.active_audio_seq = seq

    def parse_audio_chunk(self, payload: bytes) -> tuple[int, bytes]:
        if self.active_audio_seq is None:
            raise ProtocolError("binary_not_expected", "Аудио-реплика не была объявлена")
        if len(payload) <= AUDIO_SEQUENCE_BYTES:
            raise ProtocolError("invalid_audio_chunk", "Аудио-кадр не содержит PCM payload")
        seq = int.from_bytes(payload[:AUDIO_SEQUENCE_BYTES], "big", signed=False)
        if seq != self.active_audio_seq:
            raise ProtocolError("stale_audio", "Аудио-кадр относится к устаревшей реплике")
        pcm = payload[AUDIO_SEQUENCE_BYTES:]
        if len(pcm) % 2:
            raise ProtocolError("invalid_audio_chunk", "PCM S16LE должен содержать целые samples")
        return seq, pcm

    def finish_audio(self, seq: int) -> None:
        if self.active_audio_seq != seq:
            raise ProtocolError("stale_audio", "Sequence не совпадает с активной репликой")
        self.active_audio_seq = None
        self.completed_audio_seq = seq

    def interrupt(self) -> None:
        self.active_audio_seq = None
        self.pending_file = None

    def start_file(self, *, name: str, mime: str, size: int, max_bytes: int) -> None:
        if self.state is not ConnectionState.READY:
            raise ProtocolError("pair_required", "Файл требует авторизации")
        if self.pending_file is not None:
            raise ProtocolError("file_in_progress", "Предыдущий файл ещё не получен")
        if self.active_audio_seq is not None:
            raise ProtocolError("audio_in_progress", "Сначала завершите аудио-реплику")
        if size > max_bytes:
            raise ProtocolError("file_too_large", "Файл превышает допустимый размер")
        self.pending_file = PendingFile(name=name, mime=mime, size=size)

    def append_file_chunk(self, payload: bytes) -> CompletedFile | None:
        pending = self.pending_file
        if pending is None:
            raise ProtocolError("binary_not_expected", "Бинарный кадр не был объявлен")
        if not payload:
            raise ProtocolError("empty_binary", "Пустой бинарный кадр запрещён")
        if len(pending.data) + len(payload) > pending.size:
            self.pending_file = None
            raise ProtocolError("file_size_mismatch", "Получено больше объявленного размера")
        pending.data.extend(payload)
        if len(pending.data) < pending.size:
            return None
        self.pending_file = None
        return CompletedFile(name=pending.name, mime=pending.mime, data=bytes(pending.data))

    def close(self) -> None:
        self.interrupt()
        self.state = ConnectionState.CLOSED


@dataclass(slots=True)
class ClientConnection:
    """Транспортная оболочка над aiohttp WebSocket без доменной логики Hermes."""

    ws: Any
    context: ConnectionContext = field(default_factory=ConnectionContext)

    async def send_json(self, payload: dict[str, Any]) -> None:
        if self.context.state is not ConnectionState.CLOSED:
            await self.ws.send_json(payload)

    async def send_audio(self, pcm: bytes) -> None:
        if self.context.state is not ConnectionState.CLOSED:
            await self.ws.send_bytes(pcm)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.context.close()
        await self.ws.close(code=code, message=reason.encode("utf-8")[:123])
