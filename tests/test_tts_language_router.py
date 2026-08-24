from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest

from hermes_voice_gateway.tts.language_router import (
    ExplicitLanguageEngine,
    current_tts_language,
    selected_tts_language,
)


class FakeEngine:
    def __init__(self, value: bytes) -> None:
        self.value = value

    def stream(self, text: str) -> Iterator[bytes]:
        yield self.value + text.encode()


def test_explicit_router_uses_client_selected_language() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def ru_factory(section: dict[str, Any]) -> FakeEngine:
        calls.append(("ru", section))
        return FakeEngine(b"ru:")

    def en_factory(section: dict[str, Any]) -> FakeEngine:
        calls.append(("en", section))
        return FakeEngine(b"en:")

    config = {"ru": {"voice": "dmitri"}, "en": {"voice": "af_heart"}}
    with selected_tts_language("en"):
        engine = ExplicitLanguageEngine(
            config,
            piper_factory=ru_factory,
            kokoro_factory=en_factory,
        )
    assert engine.language == "en"
    assert list(engine.stream("hello")) == [b"en:hello"]
    assert calls == [("en", {"voice": "af_heart"})]
    assert current_tts_language() == "ru"


@pytest.mark.asyncio
async def test_language_context_is_isolated_between_concurrent_turns() -> None:
    ready = asyncio.Event()

    async def capture(language: str) -> str:
        with selected_tts_language(language):
            ready.set()
            await asyncio.sleep(0)
            return current_tts_language()

    ru, en = await asyncio.gather(capture("ru"), capture("en"))
    assert (ru, en) == ("ru", "en")


def test_router_rejects_missing_or_automatic_language() -> None:
    with pytest.raises(ValueError):
        with selected_tts_language("auto"):
            pass
    with selected_tts_language("en"), pytest.raises(ValueError, match="voice_explicit.en"):
        ExplicitLanguageEngine({"ru": {}}, kokoro_factory=lambda _: FakeEngine(b"en"))
