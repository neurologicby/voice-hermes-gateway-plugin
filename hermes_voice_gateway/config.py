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
        if self.heartbeat_seconds <= 0 or self.idle_timeout_seconds <= 0:
            raise ValueError("Таймауты должны быть положительными")
        if self.idle_timeout_seconds <= self.heartbeat_seconds:
            raise ValueError("idle timeout должен превышать heartbeat")
        for proxy in self.trusted_proxies:
            ip_address(proxy)
