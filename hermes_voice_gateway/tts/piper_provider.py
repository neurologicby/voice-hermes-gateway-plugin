"""Piper → PCM S16LE mono 24 kHz для streaming consumer Hermes."""

from __future__ import annotations

import importlib.util
import sys
import threading
from array import array
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Protocol, cast

from ..model_manifest import ModelManifest


class PiperConfigurationError(RuntimeError):
    """Piper или проверенная voice bundle настроены некорректно."""


class _PiperVoice(Protocol):
    def synthesize(self, text: str) -> Iterator[Any]: ...


VoiceFactory = Callable[[Path, Path], _PiperVoice]


class PiperPCMEngine:
    """Лениво загружает Piper и отдаёт bounded PCM chunks требуемого формата."""

    output_sample_rate = 24_000
    channels = 1
    sample_width = 2

    def __init__(
        self,
        model_path: str | Path,
        config_path: str | Path,
        *,
        chunk_ms: int = 100,
        voice_factory: VoiceFactory | None = None,
    ) -> None:
        self.model_path = self._verified_file(model_path, ".onnx")
        self.config_path = self._verified_file(config_path, ".json")
        if not 20 <= chunk_ms <= 500:
            raise PiperConfigurationError("Piper chunk_ms must be between 20 and 500")
        self.chunk_bytes = self.output_sample_rate * self.sample_width * chunk_ms // 1000
        self._voice_factory = voice_factory or self._load_piper_voice
        self._voice: _PiperVoice | None = None
        self._load_lock = threading.Lock()

    @staticmethod
    def _verified_file(value: str | Path, suffix: str) -> Path:
        path = Path(value).expanduser()
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise PiperConfigurationError(f"Piper artifact is unavailable: {path.name}") from exc
        if not resolved.is_file() or resolved.suffix.lower() != suffix:
            raise PiperConfigurationError(f"Invalid Piper {suffix} artifact")
        return resolved

    @staticmethod
    def _load_piper_voice(model_path: Path, config_path: Path) -> _PiperVoice:
        from piper import PiperVoice

        return cast(_PiperVoice, PiperVoice.load(model_path, config_path=config_path))

    def _get_voice(self) -> _PiperVoice:
        if self._voice is None:
            with self._load_lock:
                if self._voice is None:
                    self._voice = self._voice_factory(self.model_path, self.config_path)
        return self._voice

    def stream(self, text: str) -> Iterator[bytes]:
        if not text.strip():
            return
        source_rate: int | None = None
        pcm_parts: list[bytes] = []
        for chunk in self._get_voice().synthesize(text):
            rate = int(getattr(chunk, "sample_rate", 0))
            width = int(getattr(chunk, "sample_width", 0))
            channels = int(getattr(chunk, "sample_channels", 0))
            pcm = bytes(getattr(chunk, "audio_int16_bytes", b""))
            if rate <= 0 or width != 2 or channels != 1 or len(pcm) % 2:
                raise PiperConfigurationError("Piper returned an unsupported audio format")
            if source_rate is not None and rate != source_rate:
                raise PiperConfigurationError("Piper changed sample rate inside one utterance")
            source_rate = rate
            if pcm:
                pcm_parts.append(pcm)
        if source_rate is None or not pcm_parts:
            return
        output = _resample_s16le_mono(b"".join(pcm_parts), source_rate, self.output_sample_rate)
        for offset in range(0, len(output), self.chunk_bytes):
            yield output[offset : offset + self.chunk_bytes]


def piper_engine_from_section(section: dict[str, Any]) -> PiperPCMEngine:
    manifest_path = Path(str(section.get("manifest", "")))
    model_dir = Path(str(section.get("model_dir", "")))
    manifest = ModelManifest.load(manifest_path)
    if manifest.family != "piper":
        raise PiperConfigurationError("Configured manifest is not a Piper voice")
    artifacts = manifest.verify(model_dir)
    models = [path for path in artifacts.values() if path.suffix.lower() == ".onnx"]
    configs = [path for path in artifacts.values() if path.name.lower().endswith(".onnx.json")]
    if len(models) != 1 or len(configs) != 1:
        raise PiperConfigurationError("Piper bundle needs one ONNX model and config")
    return PiperPCMEngine(
        models[0],
        configs[0],
        chunk_ms=int(section.get("chunk_ms", 100)),
    )


def _resample_s16le_mono(pcm: bytes, source_rate: int, target_rate: int) -> bytes:
    if source_rate <= 0 or target_rate <= 0 or len(pcm) % 2:
        raise PiperConfigurationError("Invalid PCM passed to Piper resampler")
    if source_rate == target_rate:
        return pcm
    source = array("h")
    source.frombytes(pcm)
    if sys.byteorder != "little":
        source.byteswap()
    if len(source) < 2:
        return pcm
    output_count = max(1, round(len(source) * target_rate / source_rate))
    output = array("h")
    output.extend(0 for _ in range(output_count))
    scale = source_rate / target_rate
    last = len(source) - 1
    for index in range(output_count):
        position = min(index * scale, last)
        left = int(position)
        right = min(left + 1, last)
        fraction = position - left
        sample = round(source[left] + (source[right] - source[left]) * fraction)
        output[index] = max(-32_768, min(32_767, sample))
    if sys.byteorder != "little":
        output.byteswap()
    return output.tobytes()


def register_piper_provider() -> bool:
    """Регистрирует provider в фактическом streaming-реестре Hermes 0.20.5."""

    try:
        from tools.tts_streaming import (
            StreamingTTSProvider,
            register,
        )
    except ImportError:
        return False

    @register("voice_piper")
    class HermesPiperStreamer(StreamingTTSProvider):  # type: ignore[misc]
        sample_rate = 24_000
        channels = 1
        sample_width = 2

        @staticmethod
        def available() -> bool:
            try:
                return importlib.util.find_spec("piper") is not None
            except (ImportError, ValueError):
                return False

        def __init__(self, tts_config: dict[str, Any], section: dict[str, Any]) -> None:
            super().__init__(tts_config, section)
            self._engine = piper_engine_from_section(section)

        def stream(self, text: str) -> Iterator[bytes]:
            yield from self._engine.stream(text)

    return True
