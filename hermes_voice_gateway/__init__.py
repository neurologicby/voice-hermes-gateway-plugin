"""Независимое ядро Hermes VoiceGateway.

Hermes-specific entrypoint будет добавлен после проверки контрактов целевой версии.
"""

from .config import VoicePlatformConfig
from .connection import ConnectionContext, ConnectionState
from .pairing import PairingService, PairingStorePort
from .protocol import PROTOCOL_VERSION, ProtocolError, parse_control_frame

__all__ = [
    "PROTOCOL_VERSION",
    "ConnectionContext",
    "ConnectionState",
    "PairingService",
    "PairingStorePort",
    "ProtocolError",
    "VoicePlatformConfig",
    "parse_control_frame",
]
