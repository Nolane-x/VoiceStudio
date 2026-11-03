#!/usr/bin/env python3
"""Static contracts for the ZeroTTS local Vietnamese CPU benchmark."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_zerotts_local.py"
SPEC = importlib.util.spec_from_file_location("benchmark_zerotts_local", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ZeroTtsLocalBenchmarkTests(unittest.TestCase):
    def test_eight_presets_and_four_vietnamese_text_cases(self):
        MODULE.check_contract()
        self.assertEqual(len(MODULE.EXPECTED_VOICES), 8)
        self.assertEqual(len(set(MODULE.EXPECTED_VOICES)), 8)
        self.assertEqual(len(MODULE.TEXT_CASES), 4)
        self.assertEqual(MODULE.SAMPLE_RATE, 48000)

    def test_distribution_pin_and_immutable_model_revision(self):
        self.assertEqual(MODULE.PACKAGE_VERSION, "0.1.5")
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('importlib.metadata.version("zerotts")', source)
        self.assertIn("HfApi().model_info(MODEL_ID, files_metadata=False).sha", source)
        self.assertIn("revision=revision", source)
        self.assertIn('providers=["CPUExecutionProvider"]', source)

    def test_checks_both_one_shot_and_streaming_interfaces(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("tts.synthesize(text, voice=voice, timing=timing)", source)
        self.assertIn("tts.synthesize_stream(", source)
        self.assertIn("time_to_first_audio_seconds", source)
        self.assertIn("normalize_vi_text(original_text)", source)

    def test_audio_is_watermarked_and_rights_are_not_overclaimed(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("run_ffmpeg_normalize(", source)
        self.assertIn("watermark_and_verify(", source)
        self.assertIn("validate_audio(", source)
        self.assertIn('"human_review": "not_completed"', source)
        self.assertIn("encoder is not published", source)
        self.assertIn("training-source recording consent", source)

    def test_no_hosted_tts_api_or_provider_keys(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("requests.post", source)
        self.assertNotIn("httpx.post", source)
        for key in ("ELEVENLABS_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY"):
            self.assertNotIn(key, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
