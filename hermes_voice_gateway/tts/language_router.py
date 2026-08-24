"""Context-safe явный RU/EN router для параллельных voice turns."""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal, Protocol

from .kokoro_provider import kokoro_engine_from_section
from .piper_provider import piper_engine_from_section

SpeechLanguage = Literal["ru", "en"]


class PCMEngine(Protocol):
    def stream(self, text: str) -> Iterator[bytes]: ...


EngineFactory = Callable[[dict[str, Any]], PCMEngine]
_language: ContextVar[SpeechLanguage] = ContextVar("voice_tts_language", default="ru")


@contextmanager
def selected_tts_language(language: str) -> Iterator[None]:
    if language not in {"ru", "en"}:
        raise ValueError("TTS language must be explicit ru or en")
    token = _language.set(language)  # type: ignore[arg-type]
    try:
        yield
    finally:
        _language.reset(token)


def current_tts_language() -> SpeechLanguage:
    return _language.get()


class ExplicitLanguageEngine:
    """Захватывает язык в момент создания per-turn Hermes consumer."""

    def __init__(
        self,
        section: dict[str, Any],
        *,
        piper_factory: EngineFactory = piper_engine_from_section,
        kokoro_factory: EngineFactory = kokoro_engine_from_section,
    ) -> None:
        self.language = current_tts_language()
        selected = section.get(self.language)
        if not isinstance(selected, dict):
            raise ValueError(f"voice_explicit.{self.language} section is required")
        factory = piper_factory if self.language == "ru" else kokoro_factory
        self._engine = factory(selected)

    def stream(self, text: str) -> Iterator[bytes]:
        yield from self._engine.stream(text)


def register_explicit_language_provider() -> bool:
    try:
        from tools.tts_streaming import StreamingTTSProvider, register
    except ImportError:
        return False

    @register("voice_explicit")
    class HermesExplicitLanguageStreamer(StreamingTTSProvider):  # type: ignore[misc]
        sample_rate = 24_000
        channels = 1
        sample_width = 2

        @staticmethod
        def available() -> bool:
            module = "piper" if current_tts_language() == "ru" else "kokoro"
            try:
                return importlib.util.find_spec(module) is not None
            except (ImportError, ValueError):
                return False

        def __init__(self, tts_config: dict[str, Any], section: dict[str, Any]) -> None:
            super().__init__(tts_config, section)
            self._engine = ExplicitLanguageEngine(section)

        def stream(self, text: str) -> Iterator[bytes]:
            yield from self._engine.stream(text)

    return True


__all__ = [
    "ExplicitLanguageEngine",
    "current_tts_language",
    "register_explicit_language_provider",
    "selected_tts_language",
]
