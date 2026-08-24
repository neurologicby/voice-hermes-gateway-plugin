from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from hermes_voice_gateway.model_manifest import ModelArtifact, ModelManifest
from hermes_voice_gateway.sherpa_stt import SherpaStreamingSTTEngine
from hermes_voice_gateway.stt import STTUnavailable


class FakeOnlineRecognizer:
    calls: ClassVar[list[dict[str, object]]] = []

    @classmethod
    def from_t_one_ctc(cls, **kwargs: object) -> FakeRecognizer:
        cls.calls.append(kwargs)
        return FakeRecognizer()


class FakeRecognizer:
    def create_stream(self) -> object:
        return object()


def _bundle(tmp_path: Path) -> tuple[ModelManifest, Path]:
    artifacts = []
    for name, content in {
        "model.onnx": b"model",
        "tokens.txt": b"tokens",
        "LICENSE": b"license",
    }.items():
        (tmp_path / name).write_bytes(content)
        artifacts.append(ModelArtifact(name, hashlib.sha256(content).hexdigest()))
    manifest = ModelManifest(
        model_id="test-ru",
        family="t_one_ctc",
        language="ru",
        sample_rate=8000,
        license_spdx="Apache-2.0",
        license_url="https://example.test/license",
        source_url="https://example.test/model",
        source_sha256="0" * 64,
        artifacts=tuple(artifacts),
    )
    return manifest, tmp_path


def test_t_one_engine_uses_verified_paths_and_native_rate(tmp_path: Path) -> None:
    FakeOnlineRecognizer.calls.clear()
    manifest, model_dir = _bundle(tmp_path)
    sherpa = SimpleNamespace(OnlineRecognizer=FakeOnlineRecognizer)
    engine = SherpaStreamingSTTEngine(
        manifest,
        model_dir,
        sherpa_module=sherpa,
        numpy_module=object(),
    )
    call = FakeOnlineRecognizer.calls[0]
    assert call["sample_rate"] == 8000
    assert call["enable_endpoint_detection"] is True
    assert Path(str(call["model"])).name == "model.onnx"
    session = engine.create_session(seq=7, language="ru", sample_rate=16_000)
    assert session is not None


def test_engine_rejects_unsupported_language(tmp_path: Path) -> None:
    manifest, model_dir = _bundle(tmp_path)
    sherpa = SimpleNamespace(OnlineRecognizer=FakeOnlineRecognizer)
    engine = SherpaStreamingSTTEngine(
        manifest,
        model_dir,
        sherpa_module=sherpa,
        numpy_module=object(),
    )
    with pytest.raises(STTUnavailable, match="does not support"):
        engine.create_session(seq=7, language="en", sample_rate=16_000)


def test_engine_rejects_non_integral_resampling_ratio(tmp_path: Path) -> None:
    manifest, model_dir = _bundle(tmp_path)
    sherpa = SimpleNamespace(OnlineRecognizer=FakeOnlineRecognizer)
    engine = SherpaStreamingSTTEngine(
        manifest,
        model_dir,
        sherpa_module=sherpa,
        numpy_module=object(),
    )
    with pytest.raises(STTUnavailable, match="ratio"):
        engine.create_session(seq=7, language="auto", sample_rate=11_025)
