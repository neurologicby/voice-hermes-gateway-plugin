"""Локальные streaming TTS providers VoiceGateway."""

from .piper_provider import PiperPCMEngine, register_piper_provider

__all__ = ["PiperPCMEngine", "register_piper_provider"]
