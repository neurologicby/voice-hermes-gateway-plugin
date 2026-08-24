from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

HERMES_SOURCE = Path(
    os.getenv(
        "HERMES_SOURCE",
        str(Path.home() / "AppData" / "Local" / "hermes" / "hermes-agent"),
    )
)

pytestmark = pytest.mark.skipif(
    not (HERMES_SOURCE / "gateway" / "platforms" / "base.py").is_file(),
    reason="Локальный исходник Hermes недоступен",
)


def test_adapter_implements_live_hermes_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("yaml", reason="Полный Hermes dependency graph не установлен в dev venv")
    sys.path.insert(0, str(HERMES_SOURCE))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))

    from gateway import pairing as hermes_pairing
    from gateway.config import PlatformConfig
    from gateway.platform_registry import PlatformEntry, platform_registry
    from gateway.platforms.base import BasePlatformAdapter

    hermes_pairing.PAIRING_DIR = tmp_path / "pairing"
    platform_registry.register(
        PlatformEntry(
            name="voice",
            label="Voice",
            adapter_factory=lambda config: config,
            check_fn=lambda: True,
        )
    )

    from hermes_voice_gateway.adapter import VoiceGatewayAdapter

    adapter = VoiceGatewayAdapter(
        PlatformConfig(enabled=True, extra={"host": "127.0.0.1", "port": 8765})
    )

    assert isinstance(adapter, BasePlatformAdapter)
    assert adapter.platform.value == "voice"
    paths = {route.resource.canonical for route in adapter.server.app.router.routes()}
    assert {"/healthz", "/ws"} <= paths
    assert not getattr(type(adapter), "__abstractmethods__", set())

    adapter._owner_profile = "secondary"
    _ = adapter.pairing
    source = adapter.build_source(chat_id="voice:device", chat_type="dm", user_id="device")
    assert adapter._pairing_profile == "secondary"
    assert adapter._build_session_key(source).startswith("agent:secondary:")
