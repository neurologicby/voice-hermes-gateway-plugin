from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = (
    PLUGIN_ROOT / "models" / "sherpa-onnx-streaming-zipformer-en-2023-06-26-int8"
)
SAMPLE = MODEL_DIR / "0.wav"
DEPS = PLUGIN_ROOT / "deps" / "sherpa_onnx"


def test_verified_zipformer_transcribes_real_english_audio() -> None:
    if not SAMPLE.is_file() or not DEPS.is_dir():
        pytest.skip("local verified English sherpa model/deps are not installed")
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            str(PLUGIN_ROOT / "tools" / "stt_audio_probe.py"),
            str(SAMPLE),
            "--manifest",
            str(PLUGIN_ROOT / "model_manifests" / "sherpa-zipformer-en-2023-06-26-int8.json"),
            "--model-dir",
            str(MODEL_DIR),
            "--language",
            "en",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=30,
    )
    report = json.loads(completed.stdout)
    assert report["first_interim_ms"] <= 400
    assert "early nightfall" in report["final"].lower()
    assert "yellow lamps" in report["final"].lower()
