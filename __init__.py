"""Точка входа platform-плагина Hermes VoiceGateway."""

from __future__ import annotations

import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent
_DEPS_DIR = _PLUGIN_ROOT / "deps"
if _DEPS_DIR.is_dir() and str(_DEPS_DIR) not in sys.path:
    sys.path.insert(0, str(_DEPS_DIR))


def register(ctx) -> None:
    """Регистрирует платформу через проверенный API Hermes 0.20.5."""

    from .hermes_voice_gateway.adapter import (
        VoiceGatewayAdapter,
        check_requirements,
        validate_config,
    )

    ctx.register_platform(
        name="voice",
        label="Voice WebSocket Gateway",
        adapter_factory=lambda cfg: VoiceGatewayAdapter(cfg),
        check_fn=check_requirements,
        validate_config=validate_config,
        required_env=[],
        install_hint="Install plugin-local dependencies into deps/",
        allowed_users_env="VOICE_GATEWAY_ALLOWED_USERS",
        allow_all_env="VOICE_GATEWAY_ALLOW_ALL_USERS",
        max_message_length=16_384,
        emoji="🎙️",
        pii_safe=True,
        allow_update_command=True,
        platform_hint=(
            "You are communicating through a private voice WebSocket channel. "
            "Keep spoken responses concise and avoid reading tool-call details aloud."
        ),
    )


__all__ = ["register"]
