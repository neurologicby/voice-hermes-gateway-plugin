"""Независимый от Hermes контракт streaming STT и bounded worker coordination."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol


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
        *,
        auto_language: str = "ru",
    ) -> None:
        if not engines or any(language not in {"ru", "en"} for language in engines):
            raise ValueError("STT router supports only non-empty ru/en engine mapping")
        if auto_language not in engines:
            raise ValueError("auto_language must have a configured engine")
        self.engines = dict(engines)
        self.auto_language = auto_language

    def create_session(
        self,
        *,
        seq: int,
        language: str,
        sample_rate: int,
    ) -> SyncStreamingSTTSession:
        selected = self.auto_language if language == "auto" else language
        engine = self.engines.get(selected)
        if engine is None:
            raise STTUnavailable(f"STT language is not configured: {selected}")
        return engine.create_session(seq=seq, language=selected, sample_rate=sample_rate)


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
        self._sessions: dict[int, tuple[int, SyncStreamingSTTSession, Any | None]] = {}

    async def start(self, owner: int, *, seq: int, language: str) -> None:
        if self.engine is None:
            raise STTUnavailable("Streaming STT engine is not loaded")
        await self.cancel(owner)
        async with self._worker_slots:
            session, vad_session = await asyncio.to_thread(
                self._create_sessions,
                seq,
                language,
            )
        self._sessions[owner] = (seq, session, vad_session)

    async def accept(self, owner: int, *, seq: int, pcm_s16le: bytes) -> STTChunkResult:
        session, vad_session = self._session(owner, seq)
        async with self._worker_slots:
            return await asyncio.to_thread(self._accept_sync, session, vad_session, pcm_s16le)

    async def finish(self, owner: int, *, seq: int) -> STTResult:
        session, vad_session = self._session(owner, seq)
        self._sessions.pop(owner, None)
        async with self._worker_slots:
            result = await asyncio.to_thread(self._finish_sync, session, vad_session)
        if result.seq != seq:
            raise STTSessionMissing("STT engine returned a stale sequence")
        return result

    async def cancel(self, owner: int) -> None:
        entry = self._sessions.pop(owner, None)
        if entry is None:
            return
        _seq, session, vad_session = entry
        async with self._worker_slots:
            await asyncio.to_thread(self._cancel_sync, session, vad_session)

    async def close(self) -> None:
        for owner in tuple(self._sessions):
            await self.cancel(owner)

    def _session(self, owner: int, seq: int) -> tuple[SyncStreamingSTTSession, Any | None]:
        entry = self._sessions.get(owner)
        if entry is None or entry[0] != seq:
            raise STTSessionMissing("STT session does not match active sequence")
        return entry[1], entry[2]

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
