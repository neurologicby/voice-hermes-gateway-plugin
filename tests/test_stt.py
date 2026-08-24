from __future__ import annotations

import threading

import pytest

from hermes_voice_gateway.stt import (
    LanguageRoutingSTTEngine,
    STTChunkResult,
    STTCoordinator,
    STTResult,
    STTSessionMetrics,
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


class FakeVADSession:
    def __init__(self) -> None:
        self.cancelled = False

    def accept_pcm(self, pcm_s16le: bytes) -> object:
        del pcm_s16le
        return type("Result", (), {"speech_started": True, "speech_ended": True})()

    def cancel(self) -> None:
        self.cancelled = True


class FakeVADEngine:
    def __init__(self) -> None:
        self.sessions: list[FakeVADSession] = []

    def create_session(self, *, sample_rate: int) -> FakeVADSession:
        assert sample_rate == 16_000
        session = FakeVADSession()
        self.sessions.append(session)
        return session


@pytest.mark.asyncio
async def test_stt_lifecycle_runs_in_worker_thread() -> None:
    engine = FakeEngine()
    coordinator = STTCoordinator(engine, max_workers=1)
    event_loop_thread = threading.get_ident()

    await coordinator.start(1, seq=7, language="ru")
    assert await coordinator.accept(1, seq=7, pcm_s16le=b"\x01\x00") == STTChunkResult(
        interim="interim"
    )
    result = await coordinator.finish(1, seq=7)

    assert result == STTResult(seq=7, text="final", language="ru")
    metrics = coordinator.completed_metrics(1)
    assert isinstance(metrics, STTSessionMetrics)
    assert metrics.chunks == 1
    assert metrics.queue_wait_ms >= 0
    assert metrics.max_queue_wait_ms >= 0
    assert metrics.first_interim_ms is not None
    assert metrics.first_interim_ms >= 0
    assert metrics.finalization_ms >= 0
    assert metrics.to_wire()["chunks"] == 1
    assert engine.sessions[0].thread_ids
    assert event_loop_thread not in engine.sessions[0].thread_ids


@pytest.mark.asyncio
async def test_vad_endpoint_is_returned_and_cancelled_with_stt() -> None:
    vad = FakeVADEngine()
    coordinator = STTCoordinator(FakeEngine(), vad_engine=vad)
    await coordinator.start(1, seq=7, language="ru")
    update = await coordinator.accept(1, seq=7, pcm_s16le=b"\x01\x00")
    assert update == STTChunkResult(interim="interim", speech_started=True, speech_ended=True)
    await coordinator.finish(1, seq=7)
    assert vad.sessions[0].cancelled is True


@pytest.mark.asyncio
async def test_stt_rejects_stale_sequence() -> None:
    coordinator = STTCoordinator(FakeEngine())
    await coordinator.start(1, seq=7, language="ru")
    with pytest.raises(STTSessionMissing):
        await coordinator.accept(1, seq=6, pcm_s16le=b"\x00\x00")


@pytest.mark.asyncio
async def test_start_rejects_unavailable_engine() -> None:
    coordinator = STTCoordinator(None)
    with pytest.raises(STTUnavailable):
        await coordinator.start(1, seq=1, language="ru")


@pytest.mark.asyncio
async def test_cancel_is_idempotent() -> None:
    engine = FakeEngine()
    coordinator = STTCoordinator(engine)
    await coordinator.start(1, seq=1, language="en")
    await coordinator.cancel(1)
    await coordinator.cancel(1)
    assert engine.sessions[0].cancelled is True


def test_language_router_selects_explicit_engine() -> None:
    ru = FakeEngine()
    en = FakeEngine()
    router = LanguageRoutingSTTEngine({"ru": ru, "en": en})
    router.create_session(seq=1, language="ru", sample_rate=16_000)
    router.create_session(seq=2, language="en", sample_rate=16_000)
    assert ru.sessions[0].language == "ru"
    assert en.sessions[0].language == "en"


def test_language_router_rejects_unconfigured_language() -> None:
    router = LanguageRoutingSTTEngine({"ru": FakeEngine()})
    with pytest.raises(STTUnavailable, match="not configured"):
        router.create_session(seq=1, language="en", sample_rate=16_000)
