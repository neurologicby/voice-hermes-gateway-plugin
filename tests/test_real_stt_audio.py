from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = PLUGIN_ROOT / "models" / "sherpa-onnx-streaming-t-one-russian-2025-09-08"
SAMPLE = MODEL_DIR / "0.wav"
DEPS = PLUGIN_ROOT / "deps" / "sherpa_onnx"


def test_verified_t_one_model_transcribes_real_audio_with_fast_interim() -> None:
    if not SAMPLE.is_file() or not DEPS.is_dir():
        pytest.skip("local verified sherpa model/deps are not installed")
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            str(PLUGIN_ROOT / "tools" / "stt_audio_probe.py"),
            str(SAMPLE),
            "--manifest",
            str(PLUGIN_ROOT / "model_manifests" / "sherpa-t-one-ru-2025-09-08.json"),
            "--model-dir",
            str(MODEL_DIR),
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
    assert "бригада" in report["final"]
    assert "я жду" in report["final"]
