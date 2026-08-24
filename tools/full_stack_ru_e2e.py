"""Полный локальный E2E: Windows client -> Hermes VoiceGateway -> RU STT -> Piper TTS."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
import time
import wave
from array import array
from pathlib import Path
from typing import Any
from uuid import uuid4

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PLUGIN_ROOT.parent
CLIENT_ROOT = WORKSPACE_ROOT / "client"
PLUGIN_DEPS = PLUGIN_ROOT / "deps"
HERMES_SOURCE = Path(
    os.getenv(
        "HERMES_SOURCE",
        str(Path.home() / "AppData" / "Local" / "hermes" / "hermes-agent"),
    )
)
for entry in (PLUGIN_DEPS, PLUGIN_ROOT, CLIENT_ROOT, HERMES_SOURCE):
    if entry.exists():
        sys.path.insert(0, str(entry))

RU_STT_MANIFEST = PLUGIN_ROOT / "model_manifests" / "sherpa-t-one-ru-2025-09-08.json"
RU_STT_MODEL = PLUGIN_ROOT / "models" / "sherpa-onnx-streaming-t-one-russian-2025-09-08"
VAD_MANIFEST = PLUGIN_ROOT / "model_manifests" / "silero-vad-v5.json"
VAD_MODEL = PLUGIN_ROOT / "models" / "silero-vad-v5"
PIPER_MANIFEST = PLUGIN_ROOT / "model_manifests" / "piper-ru_RU-dmitri-medium.json"
PIPER_MODEL = PLUGIN_ROOT / "models" / "piper-ru_RU-dmitri-medium"
INPUT_WAV = RU_STT_MODEL / "0.wav"
OUTPUT_WAV = PLUGIN_ROOT / "build" / "full-stack-ru-e2e.wav"


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read_mono_s16le(path: Path, target_rate: int = 16_000) -> bytes:
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        source_rate = source.getframerate()
        pcm = source.readframes(source.getnframes())
    if channels != 1 or sample_width != 2:
        raise RuntimeError("control WAV must be mono signed 16-bit PCM")
    if source_rate == target_rate:
        return pcm
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    if len(samples) < 2:
        raise RuntimeError("control WAV is too short")
    output_count = round(len(samples) * target_rate / source_rate)
    output = array("h")
    scale = source_rate / target_rate
    last = len(samples) - 1
    for index in range(output_count):
        position = min(index * scale, last)
        left = int(position)
        right = min(left + 1, last)
        fraction = position - left
        output.append(round(samples[left] + (samples[right] - samples[left]) * fraction))
    if sys.byteorder != "little":
        output.byteswap()
    return output.tobytes()


class CollectingPlayback:
    """Беззвучный sink: использует реальный client router и сохраняет PCM."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.finished = asyncio.Event()
        self.format: dict[str, int] = {}
        self.audio = bytearray()
        self.interrupts = 0

    def start(self, message: dict[str, Any]) -> None:
        self.format = dict(message.get("format") or {})
        self.started.set()

    def push(self, pcm_s16le: bytes) -> None:
        self.audio.extend(pcm_s16le)

    def finish(self, message: dict[str, Any]) -> None:
        if not message.get("interrupted", False):
            self.finished.set()

    def interrupt(self) -> None:
        self.interrupts += 1

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as target:
            target.setnchannels(int(self.format["channels"]))
            target.setsampwidth(int(self.format["sample_width"]))
            target.setframerate(int(self.format["sample_rate"]))
            target.writeframes(self.audio)


async def _wait(event: asyncio.Event, name: str, duration: float) -> None:
    try:
        await asyncio.wait_for(event.wait(), timeout=duration)
    except TimeoutError as exc:
        raise RuntimeError(f"timeout waiting for {name}") from exc


async def _run() -> dict[str, Any]:
    from gateway import pairing as hermes_pairing
    from gateway.config import PlatformConfig
    from gateway.platform_registry import PlatformEntry, platform_registry
    from gateway.streaming_tts_consumer import StreamingTTSConsumer
    from voice_client.net.ws_client import ConnectionState, VoiceWSClient

    from hermes_voice_gateway.adapter import VoiceGatewayAdapter
    from hermes_voice_gateway.tts.piper_provider import register_piper_provider

    platform_registry.register(
        PlatformEntry(
            name="voice",
            label="Voice",
            adapter_factory=lambda config: config,
            check_fn=lambda: True,
        )
    )
    if not register_piper_provider():
        raise RuntimeError("voice_piper could not be registered in Hermes")

    port = _free_loopback_port()
    adapter = VoiceGatewayAdapter(
        PlatformConfig(
            enabled=True,
            typing_indicator=False,
            extra={
                "host": "127.0.0.1",
                "port": port,
                "stt_manifest": str(RU_STT_MANIFEST),
                "stt_model_dir": str(RU_STT_MODEL),
                "vad_manifest": str(VAD_MANIFEST),
                "vad_model_dir": str(VAD_MODEL),
                "stt_workers": 2,
                "stt_threads": 1,
            },
        )
    )
    response_text = "Проверка завершена. Русский голосовой канал работает."
    tts_config = {
        "provider": "voice_piper",
        "streaming": {"provider": "voice_piper"},
        "voice_piper": {
            "manifest": str(PIPER_MANIFEST),
            "model_dir": str(PIPER_MODEL),
            "chunk_ms": 100,
        },
    }
    dispatched = asyncio.Event()
    tts_completed = asyncio.Event()
    handler_result: dict[str, Any] = {}

    async def handle_inbound(event: Any) -> None:
        handler_result["transcript"] = event.text
        handler_result["message_type"] = str(
            getattr(event.message_type, "value", event.message_type)
        )
        dispatched.set()
        consumer = StreamingTTSConsumer(
            adapter,
            event.source.chat_id,
            tts_config,
            asyncio.get_running_loop(),
        )
        handler_result["tts_provider_active"] = consumer.active
        consumer.start()
        consumer.on_delta(response_text)
        consumer.finish()
        handler_result["tts_completed"] = await consumer.wait_complete(timeout=60.0)
        if handler_result["tts_completed"]:
            tts_completed.set()
        delivery = await adapter.send(event.source.chat_id, response_text)
        handler_result["text_delivered"] = delivery.success

    adapter.set_message_handler(handle_inbound)
    playback = CollectingPlayback()
    states: list[str] = []
    frames: list[dict[str, Any]] = []
    pair_required = asyncio.Event()
    pair_code_ready = asyncio.Event()
    ready = asyncio.Event()
    final_ready = asyncio.Event()
    agent_text_ready = asyncio.Event()
    vad_endpoint = asyncio.Event()
    pair_code = ""

    async def on_state(state: ConnectionState) -> None:
        states.append(state.value)
        if state is ConnectionState.PAIR_REQUIRED:
            pair_required.set()
        elif state is ConnectionState.READY:
            ready.set()

    async def on_event(frame: dict[str, Any]) -> None:
        nonlocal pair_code
        frames.append(frame)
        frame_type = frame.get("type")
        if frame_type == "pair_code":
            pair_code = str(frame["code"])
            pair_code_ready.set()
        elif frame_type == "vad_endpoint":
            vad_endpoint.set()
        elif frame_type == "final":
            final_ready.set()
        elif frame_type == "agent_text":
            agent_text_ready.set()

    device_id = str(uuid4())
    client = VoiceWSClient(
        f"ws://127.0.0.1:{port}/ws",
        device_id=device_id,
        user="Full Stack RU Probe",
        playback=playback,
        language="ru",
        client_name="voice-full-stack-ru-e2e/0.1",
        outbound_limit=512,
        on_event=on_event,
        on_state=on_state,
    )

    started_at = time.perf_counter()
    model_load_started = time.perf_counter()
    await adapter.connect()
    model_load_seconds = time.perf_counter() - model_load_started
    run_task = asyncio.create_task(client.run())
    try:
        await _wait(pair_required, "pair_required", 10.0)
        client.request_pairing("Full Stack RU Probe")
        await _wait(pair_code_ready, "pair_code", 10.0)
        approved = hermes_pairing.PairingStore().approve_code("voice", pair_code)
        if not approved:
            raise RuntimeError("Hermes rejected the generated pairing code")
        client.retry_hello()
        await _wait(ready, "hello_ok", 10.0)

        pcm = _read_mono_s16le(INPUT_WAV)
        seq = 1
        client.begin_audio(seq)
        chunk_bytes = 16_000 * 2 * 30 // 1000
        for offset in range(0, len(pcm), chunk_bytes):
            if vad_endpoint.is_set():
                break
            client.send_audio(pcm[offset : offset + chunk_bytes])
            await asyncio.sleep(0.01)
        if not vad_endpoint.is_set():
            client.end_audio()

        await _wait(final_ready, "final transcript", 45.0)
        await _wait(dispatched, "Hermes handler dispatch", 10.0)
        await _wait(playback.started, "tts_start", 30.0)
        await _wait(tts_completed, "Hermes streaming TTS completion", 60.0)
        await _wait(playback.finished, "client tts_end", 10.0)
        await _wait(agent_text_ready, "agent_text", 10.0)
        playback.save(OUTPUT_WAV)

        final_frame = next(frame for frame in frames if frame.get("type") == "final")
        agent_frame = next(frame for frame in frames if frame.get("type") == "agent_text")
        return {
            "success": True,
            "pairing": bool(approved),
            "client_ready": ConnectionState.READY.value in states,
            "server_vad_endpoint": vad_endpoint.is_set(),
            "transcript": final_frame.get("text"),
            "transcript_language": final_frame.get("lang"),
            "hermes_dispatched": handler_result.get("transcript") == final_frame.get("text"),
            "hermes_message_type": handler_result.get("message_type"),
            "agent_text": agent_frame.get("text"),
            "agent_text_delivered": handler_result.get("text_delivered"),
            "tts_provider_active": handler_result.get("tts_provider_active"),
            "tts_completed": handler_result.get("tts_completed"),
            "tts_format": playback.format,
            "tts_bytes": len(playback.audio),
            "tts_wav": str(OUTPUT_WAV),
            "model_load_seconds": round(model_load_seconds, 3),
            "total_seconds": round(time.perf_counter() - started_at, 3),
        }
    finally:
        await client.stop()
        try:
            await asyncio.wait_for(run_task, timeout=5.0)
        except TimeoutError:
            run_task.cancel()
        await adapter.disconnect()


def _required_files() -> tuple[Path, ...]:
    return (
        HERMES_SOURCE / "gateway" / "pairing.py",
        RU_STT_MANIFEST,
        RU_STT_MODEL,
        VAD_MANIFEST,
        VAD_MODEL,
        PIPER_MANIFEST,
        PIPER_MODEL,
        INPUT_WAV,
    )


def main() -> int:
    missing = [str(path) for path in _required_files() if not path.exists()]
    if missing:
        print(json.dumps({"success": False, "missing": missing}, ensure_ascii=False))
        return 2
    with tempfile.TemporaryDirectory(prefix="voice-full-stack-ru-") as temp_dir:
        os.environ["HERMES_HOME"] = temp_dir
        from gateway import pairing as hermes_pairing

        hermes_pairing.PAIRING_DIR = Path(temp_dir) / "pairing"
        result = asyncio.run(_run())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    expected = (
        result.get("success") is True
        and result.get("pairing") is True
        and result.get("client_ready") is True
        and result.get("server_vad_endpoint") is True
        and result.get("transcript_language") == "ru"
        and bool(str(result.get("transcript") or "").strip())
        and result.get("hermes_dispatched") is True
        and result.get("hermes_message_type") == "voice"
        and result.get("agent_text") == "Проверка завершена. Русский голосовой канал работает."
        and result.get("agent_text_delivered") is True
        and result.get("tts_provider_active") is True
        and result.get("tts_completed") is True
        and result.get("tts_format")
        == {"sample_rate": 24_000, "channels": 1, "sample_width": 2}
        and int(result.get("tts_bytes") or 0) > 0
    )
    return 0 if expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
