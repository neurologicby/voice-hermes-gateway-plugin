"""Run the production Silero VAD adapter against a local mono PCM WAV file."""

from __future__ import annotations

import argparse
import json
import sys
import wave
from array import array
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEPS_ROOT = PLUGIN_ROOT / "deps"
for entry in (DEPS_ROOT, PLUGIN_ROOT):
    if entry.is_dir() and str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from hermes_voice_gateway.model_manifest import ModelManifest  # noqa: E402
from hermes_voice_gateway.vad import SileroVADEngine  # noqa: E402


def _read_16khz(path: Path) -> bytes:
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("Probe requires mono PCM16 WAV")
        rate = source.getframerate()
        pcm = source.readframes(source.getnframes())
    if rate == 16_000:
        return pcm
    if rate != 8_000:
        raise ValueError("Probe currently supports 8 kHz or 16 kHz WAV")
    samples = array("h")
    samples.frombytes(pcm)
    return array("h", (sample for value in samples for sample in (value, value))).tobytes()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    args = parser.parse_args()

    pcm = _read_16khz(args.audio) + bytes(16_000 * 2)
    manifest = ModelManifest.load(args.manifest)
    session = SileroVADEngine(manifest, args.model_dir).create_session(sample_rate=16_000)
    chunk_bytes = 16_000 * 2 * 100 // 1000
    speech_started_ms: int | None = None
    speech_ended_ms: int | None = None
    for offset in range(0, len(pcm), chunk_bytes):
        update = session.accept_pcm(pcm[offset : offset + chunk_bytes])
        elapsed_ms = (offset + chunk_bytes) * 1000 // (16_000 * 2)
        if update.speech_started and speech_started_ms is None:
            speech_started_ms = elapsed_ms
        if update.speech_ended:
            speech_ended_ms = elapsed_ms
            break
    session.cancel()
    report = {
        "audio": args.audio.name,
        "speech_started_ms": speech_started_ms,
        "speech_ended_ms": speech_ended_ms,
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if speech_started_ms is not None and speech_ended_ms is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
