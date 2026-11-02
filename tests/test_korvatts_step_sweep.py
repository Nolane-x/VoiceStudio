#!/usr/bin/env python3
"""Static tests for the KorvaTTS inference-step sweep."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_korvatts_step_sweep.py"
SPEC = importlib.util.spec_from_file_location("benchmark_korvatts_step_sweep", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class StepSweepTests(unittest.TestCase):
    def test_ten_preset_four_step_matrix(self):
        MODULE.check_contract()
        self.assertEqual(len(MODULE.VOICE_IDS), 10)
        self.assertEqual(MODULE.STEPS, (8, 16, 24, 32))
        self.assertEqual(len(MODULE.VOICE_IDS) * len(MODULE.STEPS), 40)

    def test_same_seed_is_used_for_each_voice_across_steps(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("shared_seed = 20261102 + voice_index", source)
        self.assertIn("seed=shared_seed", source)

    def test_local_only_with_no_provider_calls(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('device="cpu"', source)
        self.assertIn("auto_download=False", source)
        self.assertNotIn("requests.post", source)
        for key in ("ELEVENLABS_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY"):
            self.assertNotIn(key, source)

    def test_all_audio_requires_normalization_watermark_and_validation(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("run_ffmpeg_normalize(", source)
        self.assertIn("watermark_and_verify(", source)
        self.assertIn("validate_audio(", source)
        self.assertIn('"human_review": "not_completed"', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
