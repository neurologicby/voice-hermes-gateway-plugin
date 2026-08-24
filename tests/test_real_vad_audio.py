from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SPEECH_MODEL = (
    PLUGIN_ROOT / "models" / "sherpa-onnx-streaming-t-one-russian-2025-09-08"
)
VAD_MODEL = PLUGIN_ROOT / "models" / "silero-vad-v5"
SAMPLE = SPEECH_MODEL / "0.wav"
DEPS = PLUGIN_ROOT / "deps" / "sherpa_onnx"


def test_silero_detects_speech_and_endpoint_in_real_audio() -> None:
    if not SAMPLE.is_file() or not VAD_MODEL.is_dir() or not DEPS.is_dir():
        pytest.skip("local verified sherpa VAD model/deps are not installed")
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            str(PLUGIN_ROOT / "tools" / "vad_audio_probe.py"),
            str(SAMPLE),
            "--manifest",
            str(PLUGIN_ROOT / "model_manifests" / "silero-vad-v5.json"),
            "--model-dir",
            str(VAD_MODEL),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=30,
    )
    report = json.loads(completed.stdout)
    assert report["speech_started_ms"] <= 300
    assert report["speech_ended_ms"] > report["speech_started_ms"]
