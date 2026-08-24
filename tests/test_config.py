from __future__ import annotations

import pytest

from hermes_voice_gateway.config import VoicePlatformConfig


def test_defaults_are_loopback_and_bounded() -> None:
    config = VoicePlatformConfig.from_mapping({})
    assert config.host == "127.0.0.1"
    assert config.port == 8765
    assert config.max_connections == 10


def test_public_bind_is_rejected() -> None:
    with pytest.raises(ValueError, match="loopback"):
        VoicePlatformConfig.from_mapping({"host": "0.0.0.0"})


def test_trusted_proxies_are_parsed() -> None:
    config = VoicePlatformConfig.from_mapping({"trusted_proxies": "127.0.0.1, 10.0.0.4"})
    assert config.trusted_proxies == ("127.0.0.1", "10.0.0.4")


def test_stt_model_paths_must_be_configured_together() -> None:
    with pytest.raises(ValueError, match="задаются вместе"):
        VoicePlatformConfig.from_mapping({"stt_manifest": "manifest.json"})


def test_stt_runtime_limits_are_parsed() -> None:
    config = VoicePlatformConfig.from_mapping(
        {
            "stt_manifest": "manifest.json",
            "stt_model_dir": "models/ru",
            "stt_workers": 3,
            "stt_threads": 2,
        }
    )
    assert config.stt_workers == 3
    assert config.stt_threads == 2


def test_vad_model_paths_must_be_configured_together() -> None:
    with pytest.raises(ValueError, match="задаются вместе"):
        VoicePlatformConfig.from_mapping({"vad_model_dir": "models/vad"})


def test_vad_endpoint_defaults_match_protocol() -> None:
    config = VoicePlatformConfig.from_mapping({})
    assert config.vad_threshold == 0.5
    assert config.vad_min_silence_seconds == 0.6


def test_english_stt_paths_must_be_configured_together() -> None:
    with pytest.raises(ValueError, match="задаются вместе"):
        VoicePlatformConfig.from_mapping({"stt_en_manifest": "en.json"})
