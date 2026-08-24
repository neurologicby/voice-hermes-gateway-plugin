"""Strict local model manifest and integrity verification."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .stt import STTUnavailable

ALLOWED_MODEL_LICENSES = frozenset({"Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "MIT"})


@dataclass(frozen=True, slots=True)
class ModelArtifact:
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ModelManifest:
    model_id: str
    family: str
    language: str
    sample_rate: int
    license_spdx: str
    license_url: str
    source_url: str
    artifacts: tuple[ModelArtifact, ...]

    @classmethod
    def load(cls, path: Path) -> ModelManifest:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise STTUnavailable(f"Invalid model manifest: {path}") from exc
        if not isinstance(payload, dict):
            raise STTUnavailable("Model manifest root must be an object")
        return cls._from_mapping(payload)

    @classmethod
    def _from_mapping(cls, payload: dict[str, Any]) -> ModelManifest:
        required_strings = (
            "model_id",
            "family",
            "language",
            "license_spdx",
            "license_url",
            "source_url",
        )
        values: dict[str, str] = {}
        for key in required_strings:
            value = payload.get(key)
            if not isinstance(value, str) or not value.strip():
                raise STTUnavailable(f"Model manifest field {key!r} is required")
            values[key] = value.strip()
        if values["license_spdx"] not in ALLOWED_MODEL_LICENSES:
            raise STTUnavailable(f"Model license is not allowlisted: {values['license_spdx']}")
        if values["family"] not in {"t_one_ctc", "transducer"}:
            raise STTUnavailable(f"Unsupported sherpa model family: {values['family']}")
        sample_rate = payload.get("sample_rate")
        if not isinstance(sample_rate, int) or isinstance(sample_rate, bool) or sample_rate <= 0:
            raise STTUnavailable("Model sample_rate must be a positive integer")
        raw_artifacts = payload.get("artifacts")
        if not isinstance(raw_artifacts, list) or not raw_artifacts:
            raise STTUnavailable("Model manifest requires artifacts")
        artifacts = tuple(cls._artifact(item) for item in raw_artifacts)
        if len({item.path for item in artifacts}) != len(artifacts):
            raise STTUnavailable("Model manifest contains duplicate artifact paths")
        return cls(sample_rate=sample_rate, artifacts=artifacts, **values)

    @staticmethod
    def _artifact(payload: object) -> ModelArtifact:
        if not isinstance(payload, dict):
            raise STTUnavailable("Each model artifact must be an object")
        path = payload.get("path")
        digest = payload.get("sha256")
        if not isinstance(path, str) or not _safe_relative_path(path):
            raise STTUnavailable("Model artifact path must be safe and relative")
        if not isinstance(digest, str) or len(digest) != 64:
            raise STTUnavailable(f"Model artifact {path!r} requires SHA-256")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise STTUnavailable(f"Model artifact {path!r} has invalid SHA-256") from exc
        return ModelArtifact(path=path, sha256=digest.lower())

    def verify(self, model_dir: Path) -> dict[str, Path]:
        try:
            resolved_root = model_dir.resolve(strict=True)
        except OSError as exc:
            raise STTUnavailable(f"Model directory is unavailable: {model_dir}") from exc
        verified: dict[str, Path] = {}
        for artifact in self.artifacts:
            try:
                candidate = (resolved_root / Path(artifact.path)).resolve(strict=True)
            except OSError as exc:
                raise STTUnavailable(f"Missing model artifact: {artifact.path}") from exc
            if not candidate.is_file() or not candidate.is_relative_to(resolved_root):
                raise STTUnavailable(f"Unsafe or missing model artifact: {artifact.path}")
            digest = _sha256_file(candidate)
            if digest != artifact.sha256:
                raise STTUnavailable(f"Checksum mismatch for model artifact: {artifact.path}")
            verified[artifact.path] = candidate
        if not any(Path(name).name.upper() in {"LICENSE", "NOTICE"} for name in verified):
            raise STTUnavailable("Verified model bundle must include LICENSE or NOTICE")
        return verified


def _safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts and "\\" not in value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise STTUnavailable(f"Cannot read model artifact: {path.name}") from exc
    return digest.hexdigest()
