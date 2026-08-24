"""Локальные streaming TTS providers VoiceGateway."""

from .kokoro_provider import KokoroPCMEngine, register_kokoro_provider
from .language_router import register_explicit_language_provider, selected_tts_language
from .piper_provider import PiperPCMEngine, register_piper_provider

__all__ = [
    "KokoroPCMEngine",
    "PiperPCMEngine",
    "register_explicit_language_provider",
    "register_kokoro_provider",
    "register_piper_provider",
    "selected_tts_language",
]
