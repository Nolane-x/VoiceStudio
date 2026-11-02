#!/usr/bin/env python3
"""Dependency-free tests for the KorvaTTS CPU benchmark contract."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_korvatts_cpu.py"
SPEC = importlib.util.spec_from_file_location("benchmark_korvatts_cpu", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class KorvaTtsCpuTests(unittest.TestCase):
    def test_contract_has_ten_unique_bundled_voice_styles(self):
        MODULE.check_contract()
        self.assertEqual(len(MODULE.VOICES), 10)
        self.assertEqual(len(set(MODULE.VOICES)), 10)

    def test_only_vietnamese_is_primary_language_claim(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("Main matrix: all ten bundled voice styles in the native Vietnamese mode", source)
        self.assertIn("English probes are exploratory", source)
        self.assertIn("upstream does not guarantee English quality", source)

    def test_model_and_package_are_pinned_and_local(self):
        self.assertEqual(MODULE.MODEL_ID, "dogenthq/KorvaTTS")
        self.assertEqual(MODULE.PACKAGE_VERSION, "0.1.3")
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("snapshot_download(", source)
        self.assertIn("revision=revision", source)
        self.assertIn('device="cpu"', source)
        self.assertIn("auto_download=False", source)
        for key in ("ELEVENLABS_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY"):
            self.assertNotIn(key, source)
        self.assertNotIn("requests.post", source)

    def test_audio_must_be_normalized_watermarked_and_validated(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("run_ffmpeg_normalize(", source)
        self.assertIn("watermark_and_verify(", source)
        self.assertIn("validate_audio(", source)
        self.assertIn('"human_review": "not_completed"', source)

    def test_slow_model_benchmark_is_manual_opt_in(self):
        workflow = (ROOT / ".github" / "workflows" / "voice-library.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("korvatts_benchmark == true", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn(
            "github.event.pull_request.head.ref == 'feat/korvatts-vietnamese-cpu-benchmark'",
            workflow,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
