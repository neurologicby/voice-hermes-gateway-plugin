"""Независимый от Hermes контракт streaming STT и bounded worker coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol, TypeVar

_T = TypeVar("_T")


class STTError(RuntimeError):
    """Базовая безопасная ошибка STT lifecycle."""


class STTUnavailable(STTError):
    """Движок ещё не загружен или отключён."""


class STTSessionMissing(STTError):
    """Chunk/final относится к отсутствующей либо устаревшей реплике."""


@dataclass(frozen=True, slots=True)
class STTResult:
    seq: int
    text: str
    language: str = ""


@dataclass(frozen=True, slots=True)
class STTChunkResult:
    interim: str | None = None
    speech_started: bool = False
    speech_ended: bool = False


@dataclass(frozen=True, slots=True)
class STTSessionMetrics:
    """Безопасные latency-метрики одной завершённой реплики."""

    queue_wait_ms: float
    max_queue_wait_ms: float
    first_interim_ms: float | None
    finalization_ms: float
    chunks: int

    def to_wire(self) -> dict[str, float | int | None]:
        return {
            "queue_wait_ms": round(self.queue_wait_ms, 3),
            "max_queue_wait_ms": round(self.max_queue_wait_ms, 3),
            "first_interim_ms": (
                round(self.first_interim_ms, 3) if self.first_interim_ms is not None else None
            ),
            "finalization_ms": round(self.finalization_ms, 3),
            "chunks": self.chunks,
        }


@dataclass(slots=True)
class _MutableMetrics:
    started_at: float
    queue_wait_ms: float = 0.0
    max_queue_wait_ms: float = 0.0
    first_interim_ms: float | None = None
    chunks: int = 0

    def add_wait(self, wait_ms: float) -> None:
        self.queue_wait_ms += wait_ms
        self.max_queue_wait_ms = max(self.max_queue_wait_ms, wait_ms)


@dataclass(slots=True)
class _SessionEntry:
    seq: int
    session: SyncStreamingSTTSession
    vad_session: Any | None
    metrics: _MutableMetrics


class SyncStreamingSTTSession(Protocol):
    """Синхронная inference-сессия; coordinator всегда вызывает её вне event loop."""

    def accept_pcm(self, pcm_s16le: bytes) -> str | None: ...

    def finish(self) -> STTResult: ...

    def cancel(self) -> None: ...


class StreamingSTTEngine(Protocol):
    name: str

    def create_session(
        self,
        *,
        seq: int,
        language: str,
        sample_rate: int,
    ) -> SyncStreamingSTTSession: ...


class LanguageRoutingSTTEngine:
    """Выбирает предзагруженный recognizer без двойной inference."""

    name = "language-router"

    def __init__(
        self,
        engines: dict[str, StreamingSTTEngine],
    ) -> None:
        if not engines or any(language not in {"ru", "en"} for language in engines):
            raise ValueError("STT router supports only non-empty ru/en engine mapping")
        self.engines = dict(engines)

    def create_session(
        self,
        *,
        seq: int,
        language: str,
        sample_rate: int,
    ) -> SyncStreamingSTTSession:
        engine = self.engines.get(language)
        if engine is None:
            raise STTUnavailable(f"STT language is not configured: {language}")
        return engine.create_session(seq=seq, language=language, sample_rate=sample_rate)


class STTCoordinator:
    """Изолирует sync inference в threads и ограничивает общую конкуренцию."""

    def __init__(
        self,
        engine: StreamingSTTEngine | None,
        *,
        vad_engine: Any | None = None,
        max_workers: int = 2,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers должен быть положительным")
        self.engine = engine
        self.vad_engine = vad_engine
        self._worker_slots = asyncio.Semaphore(max_workers)
        self._sessions: dict[int, _SessionEntry] = {}
        self._completed_metrics: dict[int, STTSessionMetrics] = {}

    async def start(self, owner: int, *, seq: int, language: str) -> None:
        if self.engine is None:
            raise STTUnavailable("Streaming STT engine is not loaded")
        await self.cancel(owner)
        started_at = perf_counter()
        (session, vad_session), wait_ms = await self._run_worker(
            self._create_sessions, seq, language
        )
        metrics = _MutableMetrics(started_at=started_at)
        metrics.add_wait(wait_ms)
        self._completed_metrics.pop(owner, None)
        self._sessions[owner] = _SessionEntry(seq, session, vad_session, metrics)

    async def accept(self, owner: int, *, seq: int, pcm_s16le: bytes) -> STTChunkResult:
        entry = self._session(owner, seq)
        result, wait_ms = await self._run_worker(
            self._accept_sync, entry.session, entry.vad_session, pcm_s16le
        )
        entry.metrics.add_wait(wait_ms)
        entry.metrics.chunks += 1
        if result.interim and entry.metrics.first_interim_ms is None:
            entry.metrics.first_interim_ms = (perf_counter() - entry.metrics.started_at) * 1000
        return result

    async def finish(self, owner: int, *, seq: int) -> STTResult:
        entry = self._session(owner, seq)
        self._sessions.pop(owner, None)
        finalization_started = perf_counter()
        result, wait_ms = await self._run_worker(
            self._finish_sync, entry.session, entry.vad_session
        )
        entry.metrics.add_wait(wait_ms)
        if result.seq != seq:
            raise STTSessionMissing("STT engine returned a stale sequence")
        self._completed_metrics[owner] = STTSessionMetrics(
            queue_wait_ms=entry.metrics.queue_wait_ms,
            max_queue_wait_ms=entry.metrics.max_queue_wait_ms,
            first_interim_ms=entry.metrics.first_interim_ms,
            finalization_ms=(perf_counter() - finalization_started) * 1000,
            chunks=entry.metrics.chunks,
        )
        return result

    def completed_metrics(self, owner: int) -> STTSessionMetrics | None:
        return self._completed_metrics.get(owner)

    async def cancel(self, owner: int) -> None:
        entry = self._sessions.pop(owner, None)
        if entry is None:
            return
        await self._run_worker(self._cancel_sync, entry.session, entry.vad_session)

    async def close(self) -> None:
        for owner in tuple(self._sessions):
            await self.cancel(owner)

    def _session(self, owner: int, seq: int) -> _SessionEntry:
        entry = self._sessions.get(owner)
        if entry is None or entry.seq != seq:
            raise STTSessionMissing("STT session does not match active sequence")
        return entry

    async def _run_worker(
        self, function: Callable[..., _T], *args: Any
    ) -> tuple[_T, float]:
        queued_at = perf_counter()
        async with self._worker_slots:
            wait_ms = (perf_counter() - queued_at) * 1000
            result = await asyncio.to_thread(function, *args)
        return result, wait_ms

    def _create_sessions(
        self, seq: int, language: str
    ) -> tuple[SyncStreamingSTTSession, Any | None]:
        if self.engine is None:
            raise STTUnavailable("Streaming STT engine is not loaded")
        session = self.engine.create_session(seq=seq, language=language, sample_rate=16_000)
        try:
            vad_session = (
                self.vad_engine.create_session(sample_rate=16_000)
                if self.vad_engine is not None
                else None
            )
        except Exception:
            session.cancel()
            raise
        return session, vad_session

    @staticmethod
    def _accept_sync(
        session: SyncStreamingSTTSession,
        vad_session: Any | None,
        pcm_s16le: bytes,
    ) -> STTChunkResult:
        interim = session.accept_pcm(pcm_s16le)
        if vad_session is None:
            return STTChunkResult(interim=interim)
        vad_result = vad_session.accept_pcm(pcm_s16le)
        return STTChunkResult(
            interim=interim,
            speech_started=bool(vad_result.speech_started),
            speech_ended=bool(vad_result.speech_ended),
        )

    @staticmethod
    def _finish_sync(session: SyncStreamingSTTSession, vad_session: Any | None) -> STTResult:
        if vad_session is not None:
            vad_session.cancel()
        return session.finish()

    @staticmethod
    def _cancel_sync(session: SyncStreamingSTTSession, vad_session: Any | None) -> None:
        if vad_session is not None:
            vad_session.cancel()
        session.cancel()
