"""Изолированный E2E probe pairing → approve → hello → revoke."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PLUGIN_ROOT.parent
HERMES_SOURCE = Path(
    os.getenv(
        "HERMES_SOURCE",
        str(Path.home() / "AppData" / "Local" / "hermes" / "hermes-agent"),
    )
)
DEV_SITE_PACKAGES = WORKSPACE_ROOT / ".venv" / "Lib" / "site-packages"
for entry in (DEV_SITE_PACKAGES, PLUGIN_ROOT, HERMES_SOURCE):
    if entry.exists():
        sys.path.insert(0, str(entry))


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _run() -> dict[str, object]:
    import aiohttp
    from gateway import pairing as hermes_pairing
    from gateway.config import PlatformConfig
    from gateway.platform_registry import PlatformEntry, platform_registry

    platform_registry.register(
        PlatformEntry(
            name="voice",
            label="Voice",
            adapter_factory=lambda config: config,
            check_fn=lambda: True,
        )
    )

    from hermes_voice_gateway.adapter import VoiceGatewayAdapter
    from hermes_voice_gateway.stt import STTResult

    class FakeSTTSession:
        def __init__(self, seq: int, language: str) -> None:
            self.seq = seq
            self.language = language
            self.cancelled = False

        def accept_pcm(self, pcm_s16le: bytes) -> str | None:
            return "voice interim" if pcm_s16le else None

        def finish(self) -> STTResult:
            return STTResult(seq=self.seq, text="voice final", language="ru")

        def cancel(self) -> None:
            self.cancelled = True

    class FakeSTTEngine:
        name = "fake-streaming"

        def __init__(self) -> None:
            self.sessions: list[FakeSTTSession] = []

        def create_session(self, *, seq: int, language: str, sample_rate: int):
            assert sample_rate == 16_000
            session = FakeSTTSession(seq, language)
            self.sessions.append(session)
            return session

    class FakeVADSession:
        def accept_pcm(self, pcm_s16le: bytes):
            assert pcm_s16le
            return type(
                "VADResult",
                (),
                {"speech_started": True, "speech_ended": True},
            )()

        def cancel(self) -> None:
            pass

    class FakeVADEngine:
        name = "fake-vad"

        def create_session(self, *, sample_rate: int):
            assert sample_rate == 16_000
            return FakeVADSession()

    port = _free_loopback_port()
    stt_engine = FakeSTTEngine()
    adapter = VoiceGatewayAdapter(
        PlatformConfig(enabled=True, extra={"host": "127.0.0.1", "port": port}),
        stt_engine=stt_engine,
        vad_engine=FakeVADEngine(),
    )
    inbound_events: asyncio.Queue[object] = asyncio.Queue()

    async def handle_inbound(event):
        await inbound_events.put(event)
        if getattr(event, "text", "") == "phase one text":
            return "phase one response"
        return None

    async def receive_type(ws, expected_type: str) -> dict[str, object]:
        while True:
            payload = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
            if payload.get("type") == expected_type:
                return payload

    adapter.set_message_handler(handle_inbound)
    device_id = str(uuid4())
    url = f"ws://127.0.0.1:{port}/ws"
    result: dict[str, object] = {}

    await adapter.connect()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url) as ws:
                await ws.send_json(
                    {"type": "pair_request", "device_id": device_id, "user_name": "Probe"}
                )
                pair_code = await ws.receive_json()
                result["pair_response"] = pair_code["type"]

                store = hermes_pairing.PairingStore()
                approved = store.approve_code("voice", pair_code["code"])
                result["approved"] = bool(approved and approved["user_id"] == device_id)

                await ws.send_json(
                    {
                        "type": "hello",
                        "proto": 1,
                        "device_id": device_id,
                        "user": "Probe",
                        "client": "pairing-e2e-probe/0.1",
                    }
                )
                result["hello_after_approve"] = (await ws.receive_json())["type"]

                await ws.send_json({"type": "text", "text": "phase one text"})
                text_event = await asyncio.wait_for(inbound_events.get(), timeout=2.0)
                result["text_received"] = getattr(text_event, "text", "")
                response = await receive_type(ws, "agent_text")
                result["agent_text"] = response.get("text")

                await adapter.send_draft(f"voice:{device_id}", 7, "phase one draft")
                draft = await receive_type(ws, "agent_interim")
                result["agent_interim"] = draft.get("text")

                await ws.send_json(
                    {"type": "file", "name": "probe.txt", "mime": "text/plain", "size": 5}
                )
                await ws.send_bytes(b"he")
                await ws.send_bytes(b"llo")
                file_event = await asyncio.wait_for(inbound_events.get(), timeout=2.0)
                result["file_received"] = bool(
                    getattr(file_event, "media_urls", None)
                    and getattr(file_event, "media_types", None) == ["text/plain"]
                )

                await ws.send_json({"type": "audio_start", "seq": 11, "lang": "ru"})
                await ws.send_bytes((11).to_bytes(8, "big") + b"\x01\x00\x02\x00")
                interim = await receive_type(ws, "interim")
                result["voice_interim"] = interim.get("text")
                endpoint = await receive_type(ws, "vad_endpoint")
                result["voice_vad_endpoint"] = endpoint.get("seq")
                await ws.send_json({"type": "audio_end", "seq": 11, "vad": "speech"})
                final = await receive_type(ws, "final")
                result["voice_final"] = final.get("text")
                voice_event = await asyncio.wait_for(inbound_events.get(), timeout=2.0)
                result["voice_dispatched"] = getattr(voice_event, "text", "")

                await ws.send_json({"type": "audio_start", "seq": 12, "lang": "ru"})
                await ws.send_json({"type": "interrupt"})
                await ws.send_json({"type": "ping", "t": 12})
                await receive_type(ws, "pong")
                result["voice_cancelled"] = stt_engine.sessions[-1].cancelled

                async with session.ws_connect(url) as replacement:
                    await replacement.send_json(
                        {
                            "type": "hello",
                            "proto": 1,
                            "device_id": device_id,
                            "user": "Probe",
                            "client": "pairing-e2e-probe/0.1",
                        }
                    )
                    replacement_hello = await replacement.receive_json()
                    result["reconnect_session_stable"] = (
                        replacement_hello.get("session") == f"voice:{device_id}"
                    )
                    old_frame = await asyncio.wait_for(ws.receive(), timeout=2.0)
                    result["old_connection_replaced"] = old_frame.type in {
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.CLOSING,
                    }
                    await replacement.send_json({"type": "ping", "t": 456})
                    result["reconnect_ping"] = (await replacement.receive_json()).get("t")
                    result["revoked"] = store.revoke("voice", device_id)

            async with session.ws_connect(url) as ws:
                await ws.send_json(
                    {
                        "type": "hello",
                        "proto": 1,
                        "device_id": device_id,
                        "user": "Probe",
                        "client": "pairing-e2e-probe/0.1",
                    }
                )
                result["hello_after_revoke"] = (await ws.receive_json())["type"]
    finally:
        await adapter.disconnect()
    return result


def main() -> int:
    if not (HERMES_SOURCE / "gateway" / "pairing.py").is_file():
        print(json.dumps({"error": "Hermes source tree not found"}))
        return 2
    with tempfile.TemporaryDirectory(prefix="voice-gateway-e2e-") as temp_dir:
        os.environ["HERMES_HOME"] = temp_dir
        from gateway import pairing as hermes_pairing

        hermes_pairing.PAIRING_DIR = Path(temp_dir) / "pairing"
        result = asyncio.run(_run())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    expected = {
        "pair_response": "pair_code",
        "approved": True,
        "hello_after_approve": "hello_ok",
        "text_received": "phase one text",
        "agent_text": "phase one response",
        "agent_interim": "phase one draft",
        "file_received": True,
        "voice_interim": "voice interim",
        "voice_vad_endpoint": 11,
        "voice_final": "voice final",
        "voice_dispatched": "voice final",
        "voice_cancelled": True,
        "reconnect_session_stable": True,
        "old_connection_replaced": True,
        "reconnect_ping": 456,
        "revoked": True,
        "hello_after_revoke": "pair_required",
    }
    return 0 if result == expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
