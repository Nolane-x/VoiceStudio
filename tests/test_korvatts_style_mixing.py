#!/usr/bin/env python3
"""Static contract tests for KorvaTTS style interpolation."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_korvatts_style_mixing.py"
SPEC = importlib.util.spec_from_file_location("benchmark_korvatts_style_mixing", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class StyleInterpolationTests(unittest.TestCase):
    def test_five_pairs_and_three_non_endpoint_weights(self):
        MODULE.check_contract()
        self.assertEqual(len(MODULE.VOICE_PAIRS), 5)
        self.assertEqual(len(MODULE.WEIGHTS_B), 3)
        self.assertEqual(len(MODULE.VOICE_PAIRS) * len(MODULE.WEIGHTS_B), 15)

    def test_uses_published_voice_style_tensor_api(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("from korvatts import TTS, VoiceStyle", source)
        self.assertIn("style_a.ttl * (1.0 - weight_b) + style_b.ttl * weight_b", source)
        self.assertIn("style_a.dp * (1.0 - weight_b) + style_b.dp * weight_b", source)
        self.assertIn("voice=style", source)

    def test_local_only_and_rights_gated(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('device="cpu"', source)
        self.assertIn("auto_download=False", source)
        self.assertIn('"human_review": "not_completed"', source)
        self.assertIn('"identity_claim": "none;', source)
        self.assertNotIn("requests.post", source)
        for key in ("ELEVENLABS_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY"):
            self.assertNotIn(key, source)

    def test_output_requires_normalization_watermark_and_validation(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("run_ffmpeg_normalize(", source)
        self.assertIn("watermark_and_verify(", source)
        self.assertIn("validate_audio(", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
