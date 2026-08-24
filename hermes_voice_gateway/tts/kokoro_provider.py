"""Офлайн Kokoro af_heart → PCM S16LE mono 24 кГц."""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any, Protocol, cast

from ..model_manifest import ModelManifest


class KokoroConfigurationError(RuntimeError):
    """Kokoro SDK или проверенный локальный bundle настроены неверно."""


class _Pipeline(Protocol):
    def __call__(self, text: str, **kwargs: Any) -> Iterable[Any]: ...


PipelineFactory = Callable[[Path, Path, Path], _Pipeline]


class KokoroPCMEngine:
    output_sample_rate = 24_000
    channels = 1
    sample_width = 2

    def __init__(
        self,
        model_path: Path,
        config_path: Path,
        voice_path: Path,
        *,
        speed: float = 1.0,
        chunk_ms: int = 100,
        pipeline_factory: PipelineFactory | None = None,
    ) -> None:
        self.model_path = _verified_file(model_path, ".pth")
        self.config_path = _verified_file(config_path, ".json")
        self.voice_path = _verified_file(voice_path, ".pt")
        if not 0.5 <= speed <= 2.0:
            raise KokoroConfigurationError("Kokoro speed must be between 0.5 and 2.0")
        if not 20 <= chunk_ms <= 500:
            raise KokoroConfigurationError("Kokoro chunk_ms must be between 20 and 500")
        self.speed = speed
        self.chunk_bytes = self.output_sample_rate * self.sample_width * chunk_ms // 1000
        self._pipeline = (pipeline_factory or _load_pipeline)(
            self.model_path, self.config_path, self.voice_path
        )

    def stream(self, text: str) -> Iterator[bytes]:
        if not text.strip():
            return
        for result in self._pipeline(
            text,
            voice=str(self.voice_path),
            speed=self.speed,
            split_pattern=r"\n+",
        ):
            audio = getattr(result, "audio", None)
            if audio is None and isinstance(result, tuple) and len(result) >= 3:
                audio = result[2]
            if audio is None:
                continue
            pcm = _float_audio_to_s16le(audio)
            for offset in range(0, len(pcm), self.chunk_bytes):
                yield pcm[offset : offset + self.chunk_bytes]


def kokoro_engine_from_section(section: dict[str, Any]) -> KokoroPCMEngine:
    manifest = ModelManifest.load(Path(str(section.get("manifest", ""))))
    if manifest.family != "kokoro" or manifest.language != "en":
        raise KokoroConfigurationError("Configured manifest is not English Kokoro")
    artifacts = manifest.verify(Path(str(section.get("model_dir", ""))))
    models = [path for path in artifacts.values() if path.name == "kokoro-v1_0.pth"]
    configs = [path for path in artifacts.values() if path.name == "config.json"]
    voices = [path for path in artifacts.values() if path.name == "af_heart.pt"]
    if len(models) != 1 or len(configs) != 1 or len(voices) != 1:
        raise KokoroConfigurationError("Kokoro bundle requires model, config and af_heart")
    return KokoroPCMEngine(
        models[0],
        configs[0],
        voices[0],
        speed=float(section.get("speed", 1.0)),
        chunk_ms=int(section.get("chunk_ms", 100)),
    )


def register_kokoro_provider() -> bool:
    try:
        from tools.tts_streaming import StreamingTTSProvider, register
    except ImportError:
        return False

    @register("voice_kokoro")
    class HermesKokoroStreamer(StreamingTTSProvider):  # type: ignore[misc]
        sample_rate = 24_000
        channels = 1
        sample_width = 2

        @staticmethod
        def available() -> bool:
            try:
                return importlib.util.find_spec("kokoro") is not None
            except (ImportError, ValueError):
                return False

        def __init__(self, tts_config: dict[str, Any], section: dict[str, Any]) -> None:
            super().__init__(tts_config, section)
            self._engine = kokoro_engine_from_section(section)

        def stream(self, text: str) -> Iterator[bytes]:
            yield from self._engine.stream(text)

    return True


def _load_pipeline(model_path: Path, config_path: Path, _voice_path: Path) -> _Pipeline:
    if importlib.util.find_spec("en_core_web_sm") is None:
        raise KokoroConfigurationError(
            "en-core-web-sm==3.8.0 is not installed in plugin deps; "
            "Kokoro is kept offline and will not download it at runtime"
        )
    try:
        from kokoro import KModel, KPipeline
    except ImportError as exc:
        raise KokoroConfigurationError("kokoro==0.9.4 is not installed in plugin deps") from exc
    model = KModel(
        repo_id="hexgrad/Kokoro-82M",
        config=str(config_path),
        model=str(model_path),
    ).to("cpu").eval()
    return cast(_Pipeline, KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M", model=model))


def _verified_file(path: Path, suffix: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise KokoroConfigurationError(f"Kokoro artifact is unavailable: {path.name}") from exc
    if not resolved.is_file() or resolved.suffix.lower() != suffix:
        raise KokoroConfigurationError(f"Invalid Kokoro {suffix} artifact")
    return resolved


def _float_audio_to_s16le(audio: Any) -> bytes:
    import numpy as np

    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()
    values = np.asarray(audio, dtype=np.float32).reshape(-1)
    if values.size == 0 or not np.isfinite(values).all():
        raise KokoroConfigurationError("Kokoro returned invalid audio")
    pcm = np.rint(np.clip(values, -1.0, 1.0) * 32_767).astype("<i2")
    return pcm.tobytes()


__all__ = [
    "KokoroConfigurationError",
    "KokoroPCMEngine",
    "kokoro_engine_from_section",
    "register_kokoro_provider",
]
