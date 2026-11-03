#!/usr/bin/env python3
"""Static contract tests for KorvaTTS Vietnamese stress matrix."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_korvatts_stress_matrix.py"
SPEC = importlib.util.spec_from_file_location("benchmark_korvatts_stress_matrix", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class KorvaTtsStressTests(unittest.TestCase):
    def test_five_voices_three_text_cases_three_step_counts(self):
        MODULE.check_contract()
        self.assertEqual(len(MODULE.VOICE_IDS), 5)
        self.assertEqual(len(MODULE.TEXT_CASES), 3)
        self.assertEqual(MODULE.STEP_COUNTS, (8, 16, 32))
        self.assertEqual(len(MODULE.VOICE_IDS) * len(MODULE.TEXT_CASES) * len(MODULE.STEP_COUNTS), 45)

    def test_seed_is_shared_across_step_counts_for_same_voice_and_text(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("shared_seed = 20261103 + voice_index * 100 + case_index", source)
        self.assertIn("seed=shared_seed", source)

    def test_local_only_and_no_external_tts_calls(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('device="cpu"', source)
        self.assertIn("auto_download=False", source)
        self.assertNotIn("requests.post", source)
        for key in ("ELEVENLABS_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY"):
            self.assertNotIn(key, source)

    def test_all_samples_are_normalized_watermarked_and_checked(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("run_ffmpeg_normalize(", source)
        self.assertIn("watermark_and_verify(", source)
        self.assertIn("validate_audio(", source)
        self.assertIn('"human_review": "not_completed"', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
