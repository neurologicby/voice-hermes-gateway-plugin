"""Независимый от Hermes контракт streaming STT и bounded worker coordination."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol


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


class STTCoordinator:
    """Изолирует sync inference в threads и ограничивает общую конкуренцию."""

    def __init__(self, engine: StreamingSTTEngine | None, *, max_workers: int = 2) -> None:
        if max_workers < 1:
            raise ValueError("max_workers должен быть положительным")
        self.engine = engine
        self._worker_slots = asyncio.Semaphore(max_workers)
        self._sessions: dict[int, tuple[int, SyncStreamingSTTSession]] = {}

    async def start(self, owner: int, *, seq: int, language: str) -> None:
        if self.engine is None:
            raise STTUnavailable("Streaming STT engine is not loaded")
        await self.cancel(owner)
        async with self._worker_slots:
            session = await asyncio.to_thread(
                self.engine.create_session,
                seq=seq,
                language=language,
                sample_rate=16_000,
            )
        self._sessions[owner] = (seq, session)

    async def accept(self, owner: int, *, seq: int, pcm_s16le: bytes) -> str | None:
        session = self._session(owner, seq)
        async with self._worker_slots:
            return await asyncio.to_thread(session.accept_pcm, pcm_s16le)

    async def finish(self, owner: int, *, seq: int) -> STTResult:
        session = self._session(owner, seq)
        self._sessions.pop(owner, None)
        async with self._worker_slots:
            result = await asyncio.to_thread(session.finish)
        if result.seq != seq:
            raise STTSessionMissing("STT engine returned a stale sequence")
        return result

    async def cancel(self, owner: int) -> None:
        entry = self._sessions.pop(owner, None)
        if entry is None:
            return
        _seq, session = entry
        async with self._worker_slots:
            await asyncio.to_thread(session.cancel)

    async def close(self) -> None:
        for owner in tuple(self._sessions):
            await self.cancel(owner)

    def _session(self, owner: int, seq: int) -> SyncStreamingSTTSession:
        entry = self._sessions.get(owner)
        if entry is None or entry[0] != seq:
            raise STTSessionMissing("STT session does not match active sequence")
        return entry[1]
