from __future__ import annotations

from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from hermes_voice_gateway.config import VoicePlatformConfig
from hermes_voice_gateway.connection import ClientConnection
from hermes_voice_gateway.protocol import ControlMessage, MessageType
from hermes_voice_gateway.ws_server import VoiceWSServer


class FakeAdapter:
    def __init__(self) -> None:
        self.ready = True
        self.stt_status = {"engine": "fake"}
        self.tts_status = {"engine": "fake"}
        self.received: list[MessageType] = []

    async def handle_control(self, connection: ClientConnection, message: ControlMessage) -> None:
        self.received.append(message.type)
        if message.type is MessageType.PING:
            await connection.send_json({"type": "pong", "t": message.payload["t"]})

    async def handle_binary(self, connection: ClientConnection, payload: bytes) -> None:
        del connection, payload

    def unbind(self, connection: ClientConnection) -> None:
        connection.context.close()


async def _client(adapter: FakeAdapter) -> TestClient[Any, Any]:
    app = VoiceWSServer(VoicePlatformConfig(), adapter).app  # type: ignore[arg-type]
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_healthz_reports_protocol_and_readiness() -> None:
    client = await _client(FakeAdapter())
    try:
        response = await client.get("/healthz")
        payload = await response.json()
        assert response.status == 200
        assert payload["ok"] is True
        assert payload["ready"] is True
        assert payload["protocol"] == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_ping_is_allowed_before_pairing() -> None:
    adapter = FakeAdapter()
    client = await _client(adapter)
    try:
        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "ping", "t": 123})
        assert await ws.receive_json() == {"type": "pong", "t": 123}
        assert adapter.received == [MessageType.PING]
        await ws.close()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_application_message_is_rejected_before_pairing() -> None:
    adapter = FakeAdapter()
    client = await _client(adapter)
    try:
        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "text", "text": "привет"})
        response = await ws.receive_json()
        assert response["type"] == "error"
        assert response["code"] == "pair_required"
        assert adapter.received == []
        await ws.close()
    finally:
        await client.close()
