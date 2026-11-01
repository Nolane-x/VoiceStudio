from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "voice-library" / "sources.json"
SCHEMA = ROOT / "voice-library" / "manifest.schema.json"
BUILDER = ROOT / "scripts" / "build_voice_library.py"


class VoiceLibraryContractTests(unittest.TestCase):
    def test_only_english_and_vietnamese_are_in_scope(self):
        sources = json.loads(SOURCES.read_text(encoding="utf-8"))
        self.assertEqual(sources["language_scope"], ["en", "vi"])
        self.assertEqual(set(sources["shared"]["formats"]), {"piper", "vieneu"})

    def test_piper_source_is_immutable_and_high_quality(self):
        sources = json.loads(SOURCES.read_text(encoding="utf-8"))
        english = sources["english"]
        self.assertEqual(english["model_revision"], "49a0d23f04e055f1766e5ad15ea2d121a90fa17a")
        self.assertEqual(english["model_key"], "en_US-libritts-high")
        self.assertEqual(english["model_quality"], "high")
        self.assertEqual(english["expected_speakers"], 904)
        self.assertEqual(english["model_file_size_bytes"], 136_673_811)
        self.assertEqual(english["model_file_md5"], "61d7845257f8abdc27476f606151ef8d")

    def test_vieneu_sdk_is_pinned_and_dynamic(self):
        sources = json.loads(SOURCES.read_text(encoding="utf-8"))
        vietnamese = sources["vietnamese"]
        self.assertEqual(vietnamese["sdk_package"], "vieneu==3.8.3")
        self.assertEqual(vietnamese["sample_rate"], 48_000)
        self.assertGreaterEqual(vietnamese["minimum_preset_voices"], 20)
        self.assertIn("list_preset_voices", BUILDER.read_text(encoding="utf-8"))

    def test_voice_ids_are_slugged_without_losing_vietnamese_diacritics(self):
        spec = importlib.util.spec_from_file_location("voice_library_builder", BUILDER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.slugify("Xuân Vĩnh"), "xuan-vinh")
        self.assertEqual(module.slugify("Thùy Dung"), "thuy-dung")

    def test_manifest_archive_paths_match_the_pack_layout(self):
        script = BUILDER.read_text(encoding="utf-8")
        self.assertIn('"audio_file": f"voices/{voice_id}.wav"', script)
        self.assertIn('base / language / f"{voice[\'id\']}.wav"', script)

    def test_manifest_requires_audio_hash_and_watermark(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        voice = schema["properties"]["voices"]["items"]
        required = set(voice["required"])
        self.assertTrue({
            "id", "language", "voice_identity_id", "audio_file",
            "audio_sha256", "sample_rate", "duration_seconds", "watermark",
        } <= required)
        self.assertEqual(voice["properties"]["watermark"]["const"], "verified")

    def test_every_generated_audio_uses_voice_studio_watermark_gate(self):
        script = BUILDER.read_text(encoding="utf-8")
        self.assertIn("mark_synthetic(", script)
        self.assertIn("detect_watermark(", script)
        self.assertIn('verdict.get("is_omnivoice")', script)
        self.assertIn('force=True', script)

    def test_static_contract_runs_without_model_downloads(self):
        result = subprocess.run(
            [sys.executable, str(BUILDER), "--check"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
