"""Конфигурация транспорта с безопасными значениями по умолчанию."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any


@dataclass(frozen=True, slots=True)
class VoicePlatformConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    max_connections: int = 10
    max_file_bytes: int = 50 * 1024 * 1024
    max_audio_chunk_bytes: int = 64 * 1024
    stt_workers: int = 2
    stt_threads: int = 1
    stt_manifest: str = ""
    stt_model_dir: str = ""
    stt_en_manifest: str = ""
    stt_en_model_dir: str = ""
    vad_manifest: str = ""
    vad_model_dir: str = ""
    vad_threshold: float = 0.5
    vad_min_silence_seconds: float = 0.6
    vad_min_speech_seconds: float = 0.1
    heartbeat_seconds: float = 30.0
    idle_timeout_seconds: float = 90.0
    trusted_proxies: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> VoicePlatformConfig:
        """Создаёт конфигурацию из уже разрешённого config mapping."""

        defaults = cls()
        proxies_value = values.get("trusted_proxies", ())
        if isinstance(proxies_value, str):
            proxies = tuple(part.strip() for part in proxies_value.split(",") if part.strip())
        elif isinstance(proxies_value, list | tuple):
            proxies = tuple(str(part).strip() for part in proxies_value if str(part).strip())
        else:
            raise ValueError("trusted_proxies должен быть строкой или списком")

        config = cls(
            host=str(values.get("host", defaults.host)),
            port=int(values.get("port", defaults.port)),
            max_connections=int(values.get("max_connections", defaults.max_connections)),
            max_file_bytes=int(values.get("max_file_bytes", defaults.max_file_bytes)),
            max_audio_chunk_bytes=int(
                values.get("max_audio_chunk_bytes", defaults.max_audio_chunk_bytes)
            ),
            stt_workers=int(values.get("stt_workers", defaults.stt_workers)),
            stt_threads=int(values.get("stt_threads", defaults.stt_threads)),
            stt_manifest=str(values.get("stt_manifest", defaults.stt_manifest)).strip(),
            stt_model_dir=str(values.get("stt_model_dir", defaults.stt_model_dir)).strip(),
            stt_en_manifest=str(
                values.get("stt_en_manifest", defaults.stt_en_manifest)
            ).strip(),
            stt_en_model_dir=str(
                values.get("stt_en_model_dir", defaults.stt_en_model_dir)
            ).strip(),
            vad_manifest=str(values.get("vad_manifest", defaults.vad_manifest)).strip(),
            vad_model_dir=str(values.get("vad_model_dir", defaults.vad_model_dir)).strip(),
            vad_threshold=float(values.get("vad_threshold", defaults.vad_threshold)),
            vad_min_silence_seconds=float(
                values.get("vad_min_silence_seconds", defaults.vad_min_silence_seconds)
            ),
            vad_min_speech_seconds=float(
                values.get("vad_min_speech_seconds", defaults.vad_min_speech_seconds)
            ),
            heartbeat_seconds=float(values.get("heartbeat_seconds", defaults.heartbeat_seconds)),
            idle_timeout_seconds=float(
                values.get("idle_timeout_seconds", defaults.idle_timeout_seconds)
            ),
            trusted_proxies=proxies,
        )
        config.validate()
        return config

    def validate(self) -> None:
        address = ip_address(self.host)
        if not address.is_loopback:
            raise ValueError("Плагин должен слушать loopback; внешний доступ даёт WSS proxy")
        if not 1 <= self.port <= 65_535:
            raise ValueError("port должен быть в диапазоне 1..65535")
        if not 1 <= self.max_connections <= 1_000:
            raise ValueError("max_connections должен быть в диапазоне 1..1000")
        if self.max_file_bytes < 1 or self.max_audio_chunk_bytes < 1:
            raise ValueError("Лимиты payload должны быть положительными")
        if not 1 <= self.stt_workers <= self.max_connections:
            raise ValueError("stt_workers должен быть в диапазоне 1..max_connections")
        if not 1 <= self.stt_threads <= 16:
            raise ValueError("stt_threads должен быть в диапазоне 1..16")
        if bool(self.stt_manifest) != bool(self.stt_model_dir):
            raise ValueError("stt_manifest и stt_model_dir задаются вместе")
        if bool(self.stt_en_manifest) != bool(self.stt_en_model_dir):
            raise ValueError("stt_en_manifest и stt_en_model_dir задаются вместе")
        if self.stt_en_manifest and not self.stt_manifest:
            raise ValueError("English STT требует основной stt_manifest")
        if bool(self.vad_manifest) != bool(self.vad_model_dir):
            raise ValueError("vad_manifest и vad_model_dir задаются вместе")
        if not 0 < self.vad_threshold < 1:
            raise ValueError("vad_threshold должен быть между 0 и 1")
        if self.vad_min_silence_seconds <= 0 or self.vad_min_speech_seconds <= 0:
            raise ValueError("VAD durations должны быть положительными")
        if self.heartbeat_seconds <= 0 or self.idle_timeout_seconds <= 0:
            raise ValueError("Таймауты должны быть положительными")
        if self.idle_timeout_seconds <= self.heartbeat_seconds:
            raise ValueError("idle timeout должен превышать heartbeat")
        for proxy in self.trusted_proxies:
            ip_address(proxy)
