"""Port для PairingStore Hermes и безопасный сервис pairing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class PairingStorePort(Protocol):
    """Минимальный контракт; Hermes adapter реализуется после сверки API."""

    def generate_code(self, platform: str, user_id: str, user_name: str = "") -> str | None: ...

    def is_approved(self, platform: str, user_id: str) -> bool: ...

    def revoke(self, platform: str, user_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class PairingCode:
    code: str
    expires_in: int

    def __repr__(self) -> str:
        return f"PairingCode(code=<redacted>, expires_in={self.expires_in})"


class PairingService:
    PLATFORM = "voice"

    def __init__(self, store: PairingStorePort, *, code_ttl_seconds: int = 3600) -> None:
        self._store = store
        self._code_ttl_seconds = code_ttl_seconds

    def request_code(self, device_id: str, user_name: str) -> PairingCode | None:
        code = self._store.generate_code(self.PLATFORM, device_id, user_name)
        if code is None:
            return None
        return PairingCode(code=code, expires_in=self._code_ttl_seconds)

    def is_approved(self, device_id: str) -> bool:
        return self._store.is_approved(self.PLATFORM, device_id)

    def revoke(self, device_id: str) -> bool:
        return self._store.revoke(self.PLATFORM, device_id)
