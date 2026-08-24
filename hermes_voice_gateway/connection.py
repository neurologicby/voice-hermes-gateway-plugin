"""State machine одного WebSocket-соединения."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic
from typing import Any

from .protocol import ControlMessage, MessageType, ProtocolError


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
class ConnectionContext:
    state: ConnectionState = ConnectionState.UNPAIRED
    device_id: str | None = None
    user_name: str = ""
    chat_id: str | None = None
    muted: bool = False
    paused: bool = False
    mode: str = "voice_only"
    active_audio_seq: int | None = None
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
        self.active_audio_seq = seq

    def finish_audio(self, seq: int) -> None:
        if self.active_audio_seq != seq:
            raise ProtocolError("stale_audio", "Sequence не совпадает с активной репликой")
        self.active_audio_seq = None

    def interrupt(self) -> None:
        self.active_audio_seq = None

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
