"""Проверяет импорт и instantiation адаптера в штатном Python Hermes."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PLUGIN_ROOT.parent
HERMES_SOURCE = Path(
    os.getenv(
        "HERMES_SOURCE",
        str(Path.home() / "AppData" / "Local" / "hermes" / "hermes-agent"),
    )
)
DEV_SITE_PACKAGES = WORKSPACE_ROOT / ".venv" / "Lib" / "site-packages"
PLUGIN_DEPS = PLUGIN_ROOT / "deps"
if DEV_SITE_PACKAGES.is_dir():
    sys.path.insert(0, str(DEV_SITE_PACKAGES))
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(PLUGIN_DEPS))
sys.path.insert(0, str(HERMES_SOURCE))


def main() -> int:
    if not (HERMES_SOURCE / "gateway" / "platforms" / "base.py").is_file():
        print(json.dumps({"error": "Hermes source tree not found"}))
        return 2
    with tempfile.TemporaryDirectory(prefix="voice-gateway-contract-") as temp_dir:
        os.environ["HERMES_HOME"] = temp_dir

        from gateway import pairing as hermes_pairing
        from gateway.config import PlatformConfig
        from gateway.platform_registry import PlatformEntry, platform_registry
        from gateway.platforms.base import BasePlatformAdapter

        hermes_pairing.PAIRING_DIR = Path(temp_dir) / "pairing"
        platform_registry.register(
            PlatformEntry(
                name="voice",
                label="Voice",
                adapter_factory=lambda config: config,
                check_fn=lambda: True,
            )
        )

        from hermes_voice_gateway.adapter import VoiceGatewayAdapter
        from hermes_voice_gateway.tts import register_piper_provider
        from tools import tts_streaming

        provider_registered = register_piper_provider()

        adapter = VoiceGatewayAdapter(
            PlatformConfig(enabled=True, extra={"host": "127.0.0.1", "port": 8765})
        )
        adapter._owner_profile = "contract-profile"
        _ = adapter.pairing
        source = adapter.build_source(
            chat_id="voice:contract-device",
            chat_type="dm",
            user_id="contract-device",
        )
        paths = sorted({route.resource.canonical for route in adapter.server.app.router.routes()})
        result = {
            "adapter": type(adapter).__name__,
            "base_contract": isinstance(adapter, BasePlatformAdapter),
            "abstract_methods": sorted(getattr(type(adapter), "__abstractmethods__", set())),
            "platform": adapter.platform.value,
            "pairing_profile": adapter._pairing_profile,
            "session_key": adapter._build_session_key(source),
            "routes": paths,
            "streaming_provider_registered": bool(
                provider_registered and "voice_piper" in tts_streaming._REGISTRY
            ),
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        compatible = (
            result["base_contract"]
            and not result["abstract_methods"]
            and result["pairing_profile"] == "contract-profile"
            and str(result["session_key"]).startswith("agent:contract-profile:")
            and result["streaming_provider_registered"]
        )
        return 0 if compatible else 1


if __name__ == "__main__":
    raise SystemExit(main())
