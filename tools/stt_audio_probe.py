"""Run the production sherpa adapter against a local mono PCM WAV file."""

from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from array import array
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEPS_ROOT = PLUGIN_ROOT / "deps"
for entry in (DEPS_ROOT, PLUGIN_ROOT):
    if entry.is_dir() and str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from hermes_voice_gateway.model_manifest import ModelManifest  # noqa: E402
from hermes_voice_gateway.sherpa_stt import SherpaStreamingSTTEngine  # noqa: E402


def _read_pcm16_mono(path: Path) -> tuple[int, bytes]:
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("Probe requires mono PCM16 WAV")
        return source.getframerate(), source.readframes(source.getnframes())


def _to_16khz(pcm_s16le: bytes, sample_rate: int) -> bytes:
    if sample_rate == 16_000:
        return pcm_s16le
    if sample_rate != 8_000:
        raise ValueError("Probe currently supports 8 kHz or 16 kHz WAV")
    samples = array("h")
    samples.frombytes(pcm_s16le)
    doubled = array("h", (sample for value in samples for sample in (value, value)))
    return doubled.tobytes()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--language", choices=("ru", "en"), required=True)
    args = parser.parse_args()

    source_rate, source_pcm = _read_pcm16_mono(args.audio)
    pcm = _to_16khz(source_pcm, source_rate)
    started = time.perf_counter()
    manifest = ModelManifest.load(args.manifest)
    engine = SherpaStreamingSTTEngine(manifest, args.model_dir)
    loaded = time.perf_counter()
    session = engine.create_session(seq=1, language=args.language, sample_rate=16_000)
    interims: list[str] = []
    first_interim_ms: float | None = None
    chunk_bytes = 16_000 * 2 * 300 // 1000
    for offset in range(0, len(pcm), chunk_bytes):
        interim = session.accept_pcm(pcm[offset : offset + chunk_bytes])
        if interim:
            interims.append(interim)
            if first_interim_ms is None:
                first_interim_ms = (time.perf_counter() - loaded) * 1000
    result = session.finish()
    finished = time.perf_counter()
    report = {
        "audio": args.audio.name,
        "source_rate": source_rate,
        "duration_ms": round(len(source_pcm) / (source_rate * 2) * 1000),
        "load_ms": round((loaded - started) * 1000),
        "first_interim_ms": round(first_interim_ms) if first_interim_ms is not None else None,
        "decode_ms": round((finished - loaded) * 1000),
        "interim_count": len(interims),
        "final": result.text,
        "language": result.language,
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if result.text else 1


if __name__ == "__main__":
    raise SystemExit(main())
