"""aiohttp WebSocket transport для VoiceGateway."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from aiohttp import WSMsgType, web

from .config import VoicePlatformConfig
from .connection import AUDIO_SEQUENCE_BYTES, ClientConnection
from .protocol import ProtocolError, parse_control_frame

if TYPE_CHECKING:
    from .adapter import VoiceGatewayAdapter

logger = logging.getLogger(__name__)


class VoiceWSServer:
    def __init__(self, config: VoicePlatformConfig, adapter: VoiceGatewayAdapter) -> None:
        self.config = config
        self.adapter = adapter
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._connections: set[int] = set()
        self.app = self._create_app()

    def _create_app(self) -> web.Application:
        app = web.Application(client_max_size=self.config.max_file_bytes)
        app.router.add_get("/healthz", self._healthz)
        app.router.add_get("/ws", self._handle_ws)
        return app

    async def start(self) -> None:
        if self._runner is not None:
            return
        self._runner = web.AppRunner(self.app, access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.config.host, self.config.port)
        await self._site.start()

    async def stop(self) -> None:
        runner, self._runner = self._runner, None
        self._site = None
        if runner is not None:
            await runner.cleanup()
        self._connections.clear()

    async def _healthz(self, request: web.Request) -> web.Response:
        del request
        return web.json_response(
            {
                "ok": True,
                "ready": self.adapter.ready,
                "protocol": 1,
                "connections": len(self._connections),
                "stt": self.adapter.stt_status,
                "tts": self.adapter.tts_status,
            }
        )

    async def _handle_ws(self, request: web.Request) -> web.StreamResponse:
        if len(self._connections) >= self.config.max_connections:
            return web.json_response({"error": "connection_limit"}, status=503)

        ws = web.WebSocketResponse(
            heartbeat=self.config.heartbeat_seconds,
            receive_timeout=self.config.idle_timeout_seconds,
            max_msg_size=max(
                self.config.max_audio_chunk_bytes + AUDIO_SEQUENCE_BYTES,
                64 * 1024,
            ),
        )
        await ws.prepare(request)
        connection = ClientConnection(ws)
        connection_key = id(connection)
        self._connections.add(connection_key)
        try:
            async for message in ws:
                if message.type is WSMsgType.TEXT:
                    await self._handle_text(connection, message.data)
                elif message.type is WSMsgType.BINARY:
                    frame_limit = self.config.max_audio_chunk_bytes
                    if connection.context.active_audio_seq is not None:
                        frame_limit += AUDIO_SEQUENCE_BYTES
                    if len(message.data) > frame_limit:
                        raise ProtocolError("frame_too_large", "Бинарный кадр превышает лимит")
                    await self.adapter.handle_binary(connection, bytes(message.data))
                elif message.type is WSMsgType.ERROR:
                    logger.debug("VoiceGateway WebSocket receive error: %s", ws.exception())
                    break
        except ProtocolError as exc:
            await self._send_error(connection, exc)
            await connection.close(code=1008, reason=exc.code)
        except TimeoutError:
            await connection.close(code=1001, reason="idle_timeout")
        finally:
            self._connections.discard(connection_key)
            self.adapter.unbind(connection)
        return ws

    async def _handle_text(self, connection: ClientConnection, raw: str) -> None:
        try:
            control = parse_control_frame(raw)
            if connection.context.pending_file is not None and control.type.value != "interrupt":
                connection.context.pending_file = None
                raise ProtocolError("binary_expected", "Ожидается продолжение файла")
            connection.context.authorize(control)
            await self.adapter.handle_control(connection, control)
        except ProtocolError as exc:
            await self._send_error(connection, exc)

    @staticmethod
    async def _send_error(connection: ClientConnection, exc: ProtocolError) -> None:
        await connection.send_json({"type": "error", "code": exc.code, "message": exc.message})


def safe_json(payload: dict[str, object]) -> str:
    """Детерминированное кодирование для probe/contract tests."""

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
