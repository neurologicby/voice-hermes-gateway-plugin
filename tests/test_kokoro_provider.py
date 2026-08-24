from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from hermes_voice_gateway.tts.kokoro_provider import (
    KokoroConfigurationError,
    KokoroPCMEngine,
    _load_pipeline,
)


@dataclass
class FakeResult:
    audio: np.ndarray[Any, np.dtype[np.float32]]


class FakePipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, text: str, **kwargs: Any) -> list[FakeResult]:
        self.calls.append((text, kwargs))
        return [FakeResult(np.array([-1.0, 0.0, 0.5, 1.0], dtype=np.float32))]


def _artifacts(tmp_path: Path) -> tuple[Path, Path, Path]:
    model = tmp_path / "kokoro-v1_0.pth"
    config = tmp_path / "config.json"
    voice = tmp_path / "af_heart.pt"
    model.write_bytes(b"model")
    config.write_text("{}", encoding="utf-8")
    voice.write_bytes(b"voice")
    return model, config, voice


def test_kokoro_streams_af_heart_as_pcm_24k(tmp_path: Path) -> None:
    model, config, voice = _artifacts(tmp_path)
    pipeline = FakePipeline()
    engine = KokoroPCMEngine(
        model,
        config,
        voice,
        chunk_ms=20,
        pipeline_factory=lambda *_: pipeline,
    )
    chunks = list(engine.stream("Hello"))
    samples = np.frombuffer(b"".join(chunks), dtype="<i2")
    assert samples.tolist() == [-32767, 0, 16384, 32767]
    assert engine.output_sample_rate == 24_000
    assert pipeline.calls[0][1]["voice"] == str(voice.resolve())


def test_kokoro_rejects_invalid_artifacts_and_audio(tmp_path: Path) -> None:
    model, config, voice = _artifacts(tmp_path)
    with pytest.raises(KokoroConfigurationError):
        KokoroPCMEngine(model, config, tmp_path / "missing.pt")

    class InvalidPipeline:
        def __call__(self, _text: str, **_kwargs: Any) -> list[FakeResult]:
            return [FakeResult(np.array([np.nan], dtype=np.float32))]

    engine = KokoroPCMEngine(
        model,
        config,
        voice,
        pipeline_factory=lambda *_: InvalidPipeline(),
    )
    with pytest.raises(KokoroConfigurationError):
        list(engine.stream("bad"))


def test_kokoro_refuses_runtime_language_model_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "hermes_voice_gateway.tts.kokoro_provider.importlib.util.find_spec",
        lambda _name: None,
    )

    with pytest.raises(KokoroConfigurationError, match="kept offline"):
        _load_pipeline(tmp_path / "model.pth", tmp_path / "config.json", tmp_path / "voice.pt")
