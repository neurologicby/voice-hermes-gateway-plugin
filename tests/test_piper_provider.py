from __future__ import annotations

from array import array
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_voice_gateway.tts.piper_provider import (
    PiperConfigurationError,
    PiperPCMEngine,
)


class FakeVoice:
    def __init__(self, sample_rate: int = 22_050) -> None:
        self.sample_rate = sample_rate
        self.texts: list[str] = []

    def synthesize(self, text: str):
        self.texts.append(text)
        samples = array("h", range(-100, 100))
        yield SimpleNamespace(
            sample_rate=self.sample_rate,
            sample_width=2,
            sample_channels=1,
            audio_int16_bytes=samples.tobytes(),
        )


def _artifacts(tmp_path: Path) -> tuple[Path, Path]:
    model = tmp_path / "voice.onnx"
    config = tmp_path / "voice.onnx.json"
    model.write_bytes(b"model")
    config.write_text("{}", encoding="utf-8")
    return model, config


def test_piper_is_lazy_and_resamples_to_24khz(tmp_path: Path) -> None:
    model, config = _artifacts(tmp_path)
    voice = FakeVoice()
    loads: list[tuple[Path, Path]] = []

    def factory(model_path: Path, config_path: Path) -> FakeVoice:
        loads.append((model_path, config_path))
        return voice

    engine = PiperPCMEngine(model, config, chunk_ms=20, voice_factory=factory)
    assert loads == []
    chunks = list(engine.stream("Привет"))
    assert loads == [(model.resolve(), config.resolve())]
    assert voice.texts == ["Привет"]
    assert chunks and all(len(chunk) % 2 == 0 for chunk in chunks)
    assert sum(map(len, chunks)) == round(200 * 24_000 / 22_050) * 2
    assert all(len(chunk) <= 960 for chunk in chunks)


def test_piper_rejects_missing_or_wrong_artifacts(tmp_path: Path) -> None:
    model, config = _artifacts(tmp_path)
    with pytest.raises(PiperConfigurationError):
        PiperPCMEngine(tmp_path / "missing.onnx", config)
    with pytest.raises(PiperConfigurationError):
        PiperPCMEngine(model, model)


def test_piper_rejects_non_mono_audio(tmp_path: Path) -> None:
    model, config = _artifacts(tmp_path)

    class StereoVoice(FakeVoice):
        def synthesize(self, text: str):
            del text
            yield SimpleNamespace(
                sample_rate=24_000,
                sample_width=2,
                sample_channels=2,
                audio_int16_bytes=b"\x00\x00",
            )

    engine = PiperPCMEngine(model, config, voice_factory=lambda *_: StereoVoice())
    with pytest.raises(PiperConfigurationError):
        list(engine.stream("test"))
