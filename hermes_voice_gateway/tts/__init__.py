"""Локальные streaming TTS providers VoiceGateway."""

from .kokoro_provider import KokoroPCMEngine, register_kokoro_provider
from .piper_provider import PiperPCMEngine, register_piper_provider

__all__ = [
    "KokoroPCMEngine",
    "PiperPCMEngine",
    "register_kokoro_provider",
    "register_piper_provider",
]
