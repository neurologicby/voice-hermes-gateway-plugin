from __future__ import annotations

import threading

import pytest

from hermes_voice_gateway.stt import (
    STTCoordinator,
    STTResult,
    STTSessionMissing,
    STTUnavailable,
)


class FakeSession:
    def __init__(self, seq: int, language: str) -> None:
        self.seq = seq
        self.language = language
        self.pcm = bytearray()
        self.cancelled = False
        self.thread_ids: set[int] = set()

    def accept_pcm(self, pcm_s16le: bytes) -> str | None:
        self.thread_ids.add(threading.get_ident())
        self.pcm.extend(pcm_s16le)
        return "interim" if self.pcm else None

    def finish(self) -> STTResult:
        self.thread_ids.add(threading.get_ident())
        return STTResult(seq=self.seq, text="final", language=self.language)

    def cancel(self) -> None:
        self.thread_ids.add(threading.get_ident())
        self.cancelled = True


class FakeEngine:
    name = "fake"

    def __init__(self) -> None:
        self.sessions: list[FakeSession] = []

    def create_session(self, *, seq: int, language: str, sample_rate: int) -> FakeSession:
        assert sample_rate == 16_000
        session = FakeSession(seq, language)
        self.sessions.append(session)
        return session


@pytest.mark.asyncio
async def test_stt_lifecycle_runs_in_worker_thread() -> None:
    engine = FakeEngine()
    coordinator = STTCoordinator(engine, max_workers=1)
    event_loop_thread = threading.get_ident()

    await coordinator.start(1, seq=7, language="ru")
    assert await coordinator.accept(1, seq=7, pcm_s16le=b"\x01\x00") == "interim"
    result = await coordinator.finish(1, seq=7)

    assert result == STTResult(seq=7, text="final", language="ru")
    assert engine.sessions[0].thread_ids
    assert event_loop_thread not in engine.sessions[0].thread_ids


@pytest.mark.asyncio
async def test_stt_rejects_stale_sequence() -> None:
    coordinator = STTCoordinator(FakeEngine())
    await coordinator.start(1, seq=7, language="auto")
    with pytest.raises(STTSessionMissing):
        await coordinator.accept(1, seq=6, pcm_s16le=b"\x00\x00")


@pytest.mark.asyncio
async def test_start_rejects_unavailable_engine() -> None:
    coordinator = STTCoordinator(None)
    with pytest.raises(STTUnavailable):
        await coordinator.start(1, seq=1, language="auto")


@pytest.mark.asyncio
async def test_cancel_is_idempotent() -> None:
    engine = FakeEngine()
    coordinator = STTCoordinator(engine)
    await coordinator.start(1, seq=1, language="en")
    await coordinator.cancel(1)
    await coordinator.cancel(1)
    assert engine.sessions[0].cancelled is True
