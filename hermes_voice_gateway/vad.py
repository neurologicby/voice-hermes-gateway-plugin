"""Silero VAD adapter with per-utterance state and fixed 16 kHz windows."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

from .model_manifest import ModelManifest
from .stt import STTUnavailable


@dataclass(frozen=True, slots=True)
class VADResult:
    speech_started: bool = False
    speech_ended: bool = False


class SyncVADSession(Protocol):
    def accept_pcm(self, pcm_s16le: bytes) -> VADResult: ...

    def cancel(self) -> None: ...


class VADEngine(Protocol):
    name: str

    def create_session(self, *, sample_rate: int) -> SyncVADSession: ...


class SileroVADEngine:
    name = "silero-vad"

    def __init__(
        self,
        manifest: ModelManifest,
        model_dir: Path,
        *,
        threshold: float = 0.5,
        min_silence_seconds: float = 0.6,
        min_speech_seconds: float = 0.1,
        num_threads: int = 1,
        sherpa_module: ModuleType | Any | None = None,
        numpy_module: ModuleType | Any | None = None,
    ) -> None:
        if manifest.family != "silero_vad":
            raise STTUnavailable("VAD manifest must use silero_vad family")
        if not 0 < threshold < 1:
            raise ValueError("VAD threshold must be between zero and one")
        if min_silence_seconds <= 0 or min_speech_seconds <= 0:
            raise ValueError("VAD duration thresholds must be positive")
        files = manifest.verify(model_dir)
        models = [path for path in files.values() if path.suffix == ".onnx"]
        if len(models) != 1:
            raise STTUnavailable("Silero VAD bundle requires exactly one ONNX model")
        self._model = models[0]
        self._threshold = threshold
        self._min_silence_seconds = min_silence_seconds
        self._min_speech_seconds = min_speech_seconds
        self._num_threads = num_threads
        self._sherpa = sherpa_module or _optional_import("sherpa_onnx")
        self._numpy = numpy_module or _optional_import("numpy")

    def create_session(self, *, sample_rate: int) -> SileroVADSession:
        if sample_rate != 16_000:
            raise STTUnavailable("Silero VAD requires PCM at 16 kHz")
        config = self._sherpa.VadModelConfig()
        config.silero_vad.model = str(self._model)
        config.silero_vad.threshold = self._threshold
        config.silero_vad.min_silence_duration = self._min_silence_seconds
        config.silero_vad.min_speech_duration = self._min_speech_seconds
        config.sample_rate = sample_rate
        config.num_threads = self._num_threads
        detector = self._sherpa.VoiceActivityDetector(config, buffer_size_in_seconds=30)
        return SileroVADSession(detector, self._numpy, config.silero_vad.window_size)


class SileroVADSession:
    def __init__(self, detector: Any, numpy_module: Any, window_size: int) -> None:
        self._detector = detector
        self._numpy = numpy_module
        self._window_size = window_size
        self._pending = numpy_module.empty(0, dtype="float32")
        self._started = False
        self._closed = False

    def accept_pcm(self, pcm_s16le: bytes) -> VADResult:
        if self._closed:
            raise STTUnavailable("VAD session is closed")
        samples = self._numpy.frombuffer(pcm_s16le, dtype="<i2").astype("float32") / 32768.0
        self._pending = self._numpy.concatenate((self._pending, samples))
        started_now = False
        ended = False
        while len(self._pending) >= self._window_size:
            window = self._pending[: self._window_size]
            self._pending = self._pending[self._window_size :]
            self._detector.accept_waveform(window)
            if self._detector.is_speech_detected and not self._started:
                self._started = True
                started_now = True
            while not self._detector.empty():
                self._detector.pop()
                ended = self._started
                self._started = False
        return VADResult(speech_started=started_now, speech_ended=ended)

    def cancel(self) -> None:
        if not self._closed:
            self._detector.reset()
            self._closed = True


def _optional_import(name: str) -> ModuleType:
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        missing = exc.name or "unknown module"
        raise STTUnavailable(
            f"Optional voice dependency '{name}' could not be imported "
            f"(missing or incompatible module: {missing}): {exc}"
        ) from exc
