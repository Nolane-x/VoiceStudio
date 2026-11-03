#!/usr/bin/env python3
"""Static contracts for the internal OmniVoice Vietnamese CPU clone screen."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_omnivoice_local.py"
SPEC = importlib.util.spec_from_file_location("benchmark_omnivoice_local", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class OmniVoiceLocalBenchmarkTests(unittest.TestCase):
    def test_two_synthetic_reference_voices_and_four_outputs(self):
        MODULE.check_contract()
        self.assertEqual(len(MODULE.REFERENCE_VOICES), 2)
        self.assertEqual(len({item["korva_voice"] for item in MODULE.REFERENCE_VOICES}), 2)
        self.assertEqual(len(MODULE.TARGET_TEXTS), 2)
        self.assertEqual(MODULE.NUM_STEPS, 32)

    def test_upstream_source_and_checkpoint_revisions_are_pinned(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertEqual(len(MODULE.OMNIVOICE_SOURCE_SHA), 40)
        self.assertIn("HfApi().model_info(MODEL_ID, files_metadata=False).sha", source)
        self.assertIn("HfApi().model_info(TOKENIZER_ID, files_metadata=False).sha", source)
        self.assertIn('attn_implementation="sdpa"', source)
        self.assertIn('device_map="cpu"', source)

    def test_local_reference_cloning_without_asr_or_hosted_tts(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("from korvatts import TTS", source)
        self.assertIn("model.create_voice_clone_prompt(", source)
        self.assertIn("voice_clone_prompt=prompts[reference[", source)
        self.assertIn('language="vi"', source)
        self.assertIn("load_asr=False", source)
        self.assertNotIn("requests.post", source)
        self.assertNotIn("httpx.post", source)

    def test_synthetic_references_are_not_counted_as_production_identities(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("Both reference clips are synthetic KorvaTTS preset outputs", source)
        self.assertIn("random.Random(20261103)", source)
        self.assertIn("source_path.rename(target_path)", source)
        self.assertIn("not human recordings", source)
        self.assertIn("not_declared_in_current_hugging_face_repo_metadata", source)
        self.assertIn('"human_review": "not_completed"', source)

    def test_watermark_and_validation_are_required(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("run_ffmpeg_normalize(", source)
        self.assertIn("watermark_and_verify(", source)
        self.assertIn("validate_audio(", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
