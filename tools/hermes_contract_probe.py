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
if DEV_SITE_PACKAGES.is_dir():
    sys.path.insert(0, str(DEV_SITE_PACKAGES))
sys.path.insert(0, str(PLUGIN_ROOT))
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

        adapter = VoiceGatewayAdapter(
            PlatformConfig(enabled=True, extra={"host": "127.0.0.1", "port": 8765})
        )
        paths = sorted({route.resource.canonical for route in adapter.server.app.router.routes()})
        result = {
            "adapter": type(adapter).__name__,
            "base_contract": isinstance(adapter, BasePlatformAdapter),
            "abstract_methods": sorted(getattr(type(adapter), "__abstractmethods__", set())),
            "platform": adapter.platform.value,
            "routes": paths,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["base_contract"] and not result["abstract_methods"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
