"""Run a real local TTS model and save its PCM stream as a WAV file."""

from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEPS_ROOT = PLUGIN_ROOT / "deps"
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))
if DEPS_ROOT.is_dir() and str(DEPS_ROOT) not in sys.path:
    sys.path.insert(0, str(DEPS_ROOT))

from hermes_voice_gateway.tts.kokoro_provider import (  # noqa: E402
    kokoro_engine_from_section,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--text",
        default="Hello! The offline English voice gateway is ready.",
    )
    args = parser.parse_args()

    started = time.perf_counter()
    engine = kokoro_engine_from_section(
        {
            "manifest": str(args.manifest),
            "model_dir": str(args.model_dir),
            "chunk_ms": 100,
        }
    )
    load_seconds = time.perf_counter() - started

    synthesis_started = time.perf_counter()
    chunks = list(engine.stream(args.text))
    synthesis_seconds = time.perf_counter() - synthesis_started
    if not chunks:
        raise RuntimeError("Kokoro returned no audio")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(args.output), "wb") as target:
        target.setnchannels(engine.channels)
        target.setsampwidth(engine.sample_width)
        target.setframerate(engine.output_sample_rate)
        target.writeframes(b"".join(chunks))

    audio_seconds = sum(map(len, chunks)) / (
        engine.output_sample_rate * engine.channels * engine.sample_width
    )
    print(
        f"output={args.output.resolve()} chunks={len(chunks)} "
        f"audio_seconds={audio_seconds:.3f} load_seconds={load_seconds:.3f} "
        f"synthesis_seconds={synthesis_seconds:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
