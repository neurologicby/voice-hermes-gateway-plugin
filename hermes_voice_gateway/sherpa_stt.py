"""sherpa-onnx streaming STT adapter loaded only when voice extras are installed."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType
from typing import Any

from .model_manifest import ModelManifest
from .stt import STTResult, STTUnavailable


class SherpaStreamingSTTEngine:
    name = "sherpa-onnx"

    def __init__(
        self,
        manifest: ModelManifest,
        model_dir: Path,
        *,
        num_threads: int = 1,
        sherpa_module: ModuleType | Any | None = None,
        numpy_module: ModuleType | Any | None = None,
    ) -> None:
        if num_threads < 1:
            raise ValueError("num_threads must be positive")
        files = manifest.verify(model_dir)
        self.manifest = manifest
        self._numpy = numpy_module or _optional_import("numpy")
        sherpa = sherpa_module or _optional_import("sherpa_onnx")
        tokens = _named_file(files, "tokens.txt")
        license_file = _license_file(files)
        if not license_file.is_file():
            raise STTUnavailable("Verified model license disappeared")
        if manifest.family == "t_one_ctc":
            model = _single_onnx(files)
            self._recognizer = sherpa.OnlineRecognizer.from_t_one_ctc(
                tokens=str(tokens),
                model=str(model),
                num_threads=num_threads,
                sample_rate=manifest.sample_rate,
                enable_endpoint_detection=True,
            )
        else:
            self._recognizer = sherpa.OnlineRecognizer.from_transducer(
                tokens=str(tokens),
                encoder=str(_prefixed_file(files, "encoder")),
                decoder=str(_prefixed_file(files, "decoder")),
                joiner=str(_prefixed_file(files, "joiner")),
                num_threads=num_threads,
                sample_rate=manifest.sample_rate,
                enable_endpoint_detection=True,
            )

    def create_session(self, *, seq: int, language: str, sample_rate: int) -> SherpaSTTSession:
        if language not in {"auto", self.manifest.language}:
            raise STTUnavailable(f"Model does not support language: {language}")
        if sample_rate % self.manifest.sample_rate != 0:
            raise STTUnavailable("Input/model sample-rate ratio must be an integer")
        return SherpaSTTSession(
            recognizer=self._recognizer,
            numpy_module=self._numpy,
            seq=seq,
            language=self.manifest.language,
            input_rate=sample_rate,
            model_rate=self.manifest.sample_rate,
        )


class SherpaSTTSession:
    def __init__(
        self,
        *,
        recognizer: Any,
        numpy_module: Any,
        seq: int,
        language: str,
        input_rate: int,
        model_rate: int,
    ) -> None:
        self._recognizer = recognizer
        self._numpy = numpy_module
        self._stream = recognizer.create_stream()
        self._seq = seq
        self._language = language
        self._input_rate = input_rate
        self._model_rate = model_rate
        self._last_text = ""
        self._closed = False

    def accept_pcm(self, pcm_s16le: bytes) -> str | None:
        if self._closed:
            raise STTUnavailable("STT session is closed")
        samples = self._numpy.frombuffer(pcm_s16le, dtype="<i2").astype("float32") / 32768.0
        ratio = self._input_rate // self._model_rate
        if ratio > 1:
            usable = len(samples) - (len(samples) % ratio)
            if usable == 0:
                return None
            samples = samples[:usable].reshape(-1, ratio).mean(axis=1)
        self._stream.accept_waveform(self._model_rate, samples)
        self._decode_ready()
        text = self._result_text()
        if text and text != self._last_text:
            self._last_text = text
            return text
        return None

    def finish(self) -> STTResult:
        if not self._closed:
            tail = self._numpy.zeros(int(self._model_rate * 0.5), dtype="float32")
            self._stream.accept_waveform(self._model_rate, tail)
            self._stream.input_finished()
            self._decode_ready()
            self._last_text = self._result_text() or self._last_text
            self._closed = True
        return STTResult(seq=self._seq, text=self._last_text, language=self._language)

    def cancel(self) -> None:
        if not self._closed:
            reset = getattr(self._recognizer, "reset", None)
            if reset is not None:
                reset(self._stream)
            self._closed = True

    def _decode_ready(self) -> None:
        while self._recognizer.is_ready(self._stream):
            self._recognizer.decode_stream(self._stream)

    def _result_text(self) -> str:
        getter = getattr(self._recognizer, "get_result_all", None)
        result = (
            getter(self._stream)
            if getter is not None
            else self._recognizer.get_result(self._stream)
        )
        return str(result.text).strip()


def _optional_import(name: str) -> ModuleType:
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise STTUnavailable(f"Optional voice dependency is missing: {name}") from exc


def _named_file(files: dict[str, Path], name: str) -> Path:
    matches = [path for path in files.values() if path.name == name]
    if len(matches) != 1:
        raise STTUnavailable(f"Model bundle requires exactly one {name}")
    return matches[0]


def _license_file(files: dict[str, Path]) -> Path:
    matches = [path for path in files.values() if path.name.upper() in {"LICENSE", "NOTICE"}]
    if not matches:
        raise STTUnavailable("Model bundle requires LICENSE or NOTICE")
    return matches[0]


def _single_onnx(files: dict[str, Path]) -> Path:
    matches = [path for path in files.values() if path.suffix == ".onnx"]
    if len(matches) != 1:
        raise STTUnavailable("T-One bundle requires exactly one ONNX model")
    return matches[0]


def _prefixed_file(files: dict[str, Path], prefix: str) -> Path:
    matches = [
        path
        for path in files.values()
        if path.name.startswith(prefix) and path.suffix == ".onnx"
    ]
    if len(matches) != 1:
        raise STTUnavailable(f"Transducer bundle requires exactly one {prefix} ONNX model")
    return matches[0]
