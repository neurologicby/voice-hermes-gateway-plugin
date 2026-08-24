from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hermes_voice_gateway.model_manifest import ModelManifest
from hermes_voice_gateway.stt import STTUnavailable


def _write_manifest(model_dir: Path, *, license_spdx: str = "Apache-2.0") -> Path:
    files = {
        "model.onnx": b"model",
        "tokens.txt": b"tokens",
        "LICENSE": b"Apache License 2.0",
    }
    artifacts = []
    for name, content in files.items():
        (model_dir / name).write_bytes(content)
        artifacts.append({"path": name, "sha256": hashlib.sha256(content).hexdigest()})
    manifest_path = model_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "model_id": "test-ru",
                "family": "t_one_ctc",
                "language": "ru",
                "sample_rate": 8000,
                "license_spdx": license_spdx,
                "license_url": "https://example.test/license",
                "source_url": "https://example.test/model",
                "artifacts": artifacts,
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_manifest_verifies_every_artifact_and_license(tmp_path: Path) -> None:
    manifest = ModelManifest.load(_write_manifest(tmp_path))
    verified = manifest.verify(tmp_path)
    assert set(verified) == {"model.onnx", "tokens.txt", "LICENSE"}


def test_manifest_rejects_non_allowlisted_license(tmp_path: Path) -> None:
    path = _write_manifest(tmp_path, license_spdx="LicenseRef-Unknown")
    with pytest.raises(STTUnavailable, match="not allowlisted"):
        ModelManifest.load(path)


def test_manifest_rejects_checksum_mismatch(tmp_path: Path) -> None:
    manifest = ModelManifest.load(_write_manifest(tmp_path))
    (tmp_path / "model.onnx").write_bytes(b"tampered")
    with pytest.raises(STTUnavailable, match="Checksum mismatch"):
        manifest.verify(tmp_path)


def test_manifest_rejects_path_traversal(tmp_path: Path) -> None:
    path = _write_manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["artifacts"][0]["path"] = "../model.onnx"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(STTUnavailable, match="safe and relative"):
        ModelManifest.load(path)
