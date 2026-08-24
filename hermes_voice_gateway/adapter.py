"""Hermes 0.20.5 platform adapter для VoiceGateway."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from gateway.config import Platform, PlatformConfig
from gateway.pairing import PairingStore
from gateway.platforms.base import (
    AudioFormat,
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    SendResult,
    StreamingTTSHandle,
    cache_media_bytes,
)
from gateway.session import build_session_key

from .config import VoicePlatformConfig
from .connection import ClientConnection, CompletedFile, ConnectionState
from .pairing import PairingService
from .protocol import ControlMessage, ProtocolError
from .protocol import MessageType as WireMessageType
from .ws_server import VoiceWSServer


@dataclass
class VoiceStreamingTTSHandle(StreamingTTSHandle):
    stream_id: str = ""
    connection: ClientConnection | None = None


class VoiceGatewayAdapter(BasePlatformAdapter):
    """WebSocket-платформа, использующая только штатные расширения Hermes."""

    supports_status_text = True

    def __init__(self, config: PlatformConfig):
        super().__init__(config=config, platform=Platform("voice"))
        self.voice_config = VoicePlatformConfig.from_mapping(getattr(config, "extra", {}) or {})
        self._pairing_profile: str | None = None
        self._pairing_service: PairingService | None = None
        self.server = VoiceWSServer(self.voice_config, self)
        self._connections_by_chat: dict[str, ClientConnection] = {}
        self.ready = False
        self.stt_status: dict[str, Any] = {"engine": "unloaded"}
        self.tts_status: dict[str, Any] = {"engine": "unloaded"}

    @property
    def pairing(self) -> PairingService:
        """Возвращает PairingStore, изолированный в текущем Hermes profile."""

        profile = getattr(self, "_owner_profile", None)
        if self._pairing_service is None or profile != self._pairing_profile:
            self._pairing_service = PairingService(PairingStore(profile=profile))
            self._pairing_profile = profile
        return self._pairing_service

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        del is_reconnect
        await self.server.start()
        self.ready = True
        self._mark_connected()
        return True

    async def disconnect(self) -> None:
        self.ready = False
        await self.server.stop()
        self._connections_by_chat.clear()
        self._mark_disconnected()

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        del reply_to, metadata
        connection = self._connections_by_chat.get(chat_id)
        if connection is None:
            return SendResult(
                success=False,
                error="VoiceGateway client is disconnected",
                retryable=True,
            )
        await connection.send_json({"type": "agent_text", "text": content})
        return SendResult(success=True, message_id=str(uuid4()))

    async def send_draft(
        self,
        chat_id: str,
        draft_id: int,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        del metadata
        connection = self._connections_by_chat.get(chat_id)
        if connection is None:
            return SendResult(
                success=False,
                error="VoiceGateway client is disconnected",
                retryable=True,
            )
        await connection.send_json(
            {"type": "agent_interim", "draft_id": draft_id, "text": content}
        )
        return SendResult(success=True, message_id=str(draft_id))

    async def send_typing(self, chat_id: str, metadata: dict[str, Any] | None = None) -> None:
        del metadata
        connection = self._connections_by_chat.get(chat_id)
        if connection is not None:
            status = getattr(self, "_status_text", {}).get(chat_id, "")
            await connection.send_json({"type": "agent_interim", "text": status})

    async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
        connection = self._connections_by_chat.get(chat_id)
        return {
            "name": connection.context.user_name if connection else chat_id,
            "type": "dm",
            "chat_id": chat_id,
        }

    def supports_streaming_tts(self, chat_id: str, audio_format: AudioFormat) -> bool:
        return (
            chat_id in self._connections_by_chat
            and audio_format.sample_rate == 24_000
            and audio_format.channels == 1
            and audio_format.sample_width == 2
        )

    async def begin_streaming_tts(
        self,
        chat_id: str,
        audio_format: AudioFormat,
        metadata: dict[str, Any] | None = None,
    ) -> VoiceStreamingTTSHandle | None:
        del metadata
        connection = self._connections_by_chat.get(chat_id)
        if connection is None or not self.supports_streaming_tts(chat_id, audio_format):
            return None
        handle = VoiceStreamingTTSHandle(
            chat_id=chat_id,
            audio_format=audio_format,
            stream_id=str(uuid4()),
            connection=connection,
        )
        await connection.send_json(
            {
                "type": "tts_start",
                "stream_id": handle.stream_id,
                "format": {"sample_rate": 24_000, "channels": 1, "sample_width": 2},
            }
        )
        return handle

    async def write_streaming_tts(self, handle: StreamingTTSHandle, chunk: bytes) -> None:
        if handle.aborted or not chunk:
            return
        if not isinstance(handle, VoiceStreamingTTSHandle) or handle.connection is None:
            return
        await handle.connection.send_audio(chunk)
        handle.audible = True

    async def finish_streaming_tts(
        self, handle: StreamingTTSHandle, *, interrupted: bool = False
    ) -> None:
        if not isinstance(handle, VoiceStreamingTTSHandle) or handle.connection is None:
            return
        await handle.connection.send_json(
            {"type": "tts_end", "stream_id": handle.stream_id, "interrupted": interrupted}
        )

    async def abort_streaming_tts(
        self, handle: StreamingTTSHandle, error: str | None = None
    ) -> None:
        if handle.aborted:
            return
        handle.aborted = True
        if isinstance(handle, VoiceStreamingTTSHandle) and handle.connection is not None:
            await handle.connection.send_json(
                {
                    "type": "tts_end",
                    "stream_id": handle.stream_id,
                    "interrupted": True,
                    "error": bool(error),
                }
            )

    async def handle_control(self, connection: ClientConnection, message: ControlMessage) -> None:
        handlers = {
            WireMessageType.PAIR_REQUEST: self._on_pair_request,
            WireMessageType.HELLO: self._on_hello,
            WireMessageType.PING: self._on_ping,
            WireMessageType.TEST: self._on_test,
            WireMessageType.TEXT: self._on_text,
            WireMessageType.FILE: self._on_file,
            WireMessageType.INTERRUPT: self._on_interrupt,
        }
        handler = handlers.get(message.type)
        if handler is None:
            raise ProtocolError("not_implemented", "Сообщение будет поддержано в следующей фазе")
        await handler(connection, message.payload)

    async def handle_binary(self, connection: ClientConnection, payload: bytes) -> None:
        completed = connection.context.append_file_chunk(payload)
        if completed is not None:
            await self._dispatch_file(connection, completed)

    async def _on_pair_request(self, connection: ClientConnection, payload: dict[str, Any]) -> None:
        code = self.pairing.request_code(payload["device_id"], payload["user_name"])
        if code is None:
            raise ProtocolError("pairing_rate_limited", "Новый pairing-код временно недоступен")
        connection.context.device_id = payload["device_id"]
        connection.context.user_name = payload["user_name"]
        await connection.send_json(
            {"type": "pair_code", "code": code.code, "expires_in": code.expires_in}
        )

    async def _on_hello(self, connection: ClientConnection, payload: dict[str, Any]) -> None:
        device_id = payload["device_id"]
        if not self.pairing.is_approved(device_id):
            await connection.send_json({"type": "pair_required"})
            return
        user_name = payload["user"]
        chat_id = f"voice:{device_id}"
        connection.context.mark_ready(device_id=device_id, user_name=user_name, chat_id=chat_id)
        previous = self._connections_by_chat.get(chat_id)
        self._connections_by_chat[chat_id] = connection
        if previous is not None and previous is not connection:
            await previous.close(code=1000, reason="replaced")
        await connection.send_json({"type": "hello_ok", "session": chat_id, "proto": 1})

    @staticmethod
    async def _on_ping(connection: ClientConnection, payload: dict[str, Any]) -> None:
        await connection.send_json({"type": "pong", "t": payload["t"]})

    async def _on_test(self, connection: ClientConnection, payload: dict[str, Any]) -> None:
        del payload
        await connection.send_json(
            {
                "type": "test_ok",
                "stt": self.stt_status,
                "tts": self.tts_status,
                "models_loaded": self.ready,
            }
        )

    async def _on_text(self, connection: ClientConnection, payload: dict[str, Any]) -> None:
        context = connection.context
        if context.state is not ConnectionState.READY or not context.chat_id:
            raise ProtocolError("pair_required", "Текст требует pairing")
        source = self.build_source(
            chat_id=context.chat_id,
            chat_name=context.user_name,
            chat_type="dm",
            user_id=context.device_id,
            user_name=context.user_name,
        )
        event = MessageEvent(
            text=payload["text"],
            message_type=MessageType.TEXT,
            source=source,
            raw_message={"transport": "voice-ws"},
        )
        await self.handle_message(event)

    async def _on_file(self, connection: ClientConnection, payload: dict[str, Any]) -> None:
        connection.context.start_file(
            name=payload["name"],
            mime=payload["mime"],
            size=payload["size"],
            max_bytes=self.voice_config.max_file_bytes,
        )

    async def _dispatch_file(
        self, connection: ClientConnection, completed: CompletedFile
    ) -> None:
        context = connection.context
        if context.state is not ConnectionState.READY or not context.chat_id:
            raise ProtocolError("pair_required", "Файл требует pairing")
        cached = cache_media_bytes(
            completed.data,
            filename=completed.name,
            mime_type=completed.mime,
        )
        if cached is None:
            raise ProtocolError("invalid_file", "Содержимое файла не соответствует типу")
        message_types = {
            "image": MessageType.PHOTO,
            "video": MessageType.VIDEO,
            "audio": MessageType.AUDIO,
            "document": MessageType.DOCUMENT,
        }
        source = self.build_source(
            chat_id=context.chat_id,
            chat_name=context.user_name,
            chat_type="dm",
            user_id=context.device_id,
            user_name=context.user_name,
        )
        event = MessageEvent(
            text=cached.context_note(),
            message_type=message_types[cached.kind],
            source=source,
            raw_message={
                "transport": "voice-ws",
                "file_name": completed.name,
                "mime": cached.media_type,
            },
            media_urls=[cached.path],
            media_types=[cached.media_type],
        )
        await self.handle_message(event)

    async def _on_interrupt(self, connection: ClientConnection, payload: dict[str, Any]) -> None:
        del payload
        connection.context.interrupt()
        if connection.context.chat_id:
            source = self.build_source(
                chat_id=connection.context.chat_id,
                chat_name=connection.context.user_name,
                chat_type="dm",
                user_id=connection.context.device_id,
                user_name=connection.context.user_name,
            )
            await self.interrupt_session_activity(
                self._build_session_key(source), connection.context.chat_id
            )

    def _build_session_key(self, source: Any) -> str:
        """Строит тот же ключ, который BasePlatformAdapter использует для turn."""

        extra = getattr(self.config, "extra", {}) or {}
        profile_resolver = getattr(self, "_session_key_profile", None)
        profile = (
            profile_resolver(source)
            if callable(profile_resolver)
            else getattr(self, "_owner_profile", None)
        )
        return build_session_key(
            source,
            group_sessions_per_user=bool(extra.get("group_sessions_per_user", True)),
            thread_sessions_per_user=bool(extra.get("thread_sessions_per_user", False)),
            profile=profile,
        )

    def unbind(self, connection: ClientConnection) -> None:
        chat_id = connection.context.chat_id
        if chat_id and self._connections_by_chat.get(chat_id) is connection:
            self._connections_by_chat.pop(chat_id, None)
        connection.context.close()


def check_requirements() -> bool:
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        return False
    return True


def validate_config(config: PlatformConfig) -> bool:
    if os.getenv("VOICE_GATEWAY_ENABLED", "true").strip().lower() in {"0", "false", "no"}:
        return False
    try:
        VoicePlatformConfig.from_mapping(getattr(config, "extra", {}) or {})
    except (TypeError, ValueError):
        return False
    return True
