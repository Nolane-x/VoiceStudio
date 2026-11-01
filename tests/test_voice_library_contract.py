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
        self.assertEqual(set(sources["shared"]["formats"]), {"piper", "vieneu", "kokoro"})

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


    def test_kokoro_vietnamese_candidate_is_quarantined_until_voice_rights_are_verified(self):
        registry = json.loads((ROOT / "voice-library" / "expansion-sources.json").read_text(encoding="utf-8"))
        candidate = next(
            row for row in registry["research_only_or_blocked"]
            if row["id"] == "kokoro-vietnamese-community"
        )
        self.assertEqual(candidate["listed_voicepack_count"], 14)
        self.assertEqual(candidate["repository_license"], "Apache-2.0")
        self.assertFalse(candidate["production_eligible"])
        self.assertEqual(candidate["status"], "research_only_blocked_pending_speaker_consent_and_dataset_provenance")

    def test_noncommercial_vietnamese_f5_model_is_not_a_monetized_production_candidate(self):
        registry = json.loads((ROOT / "voice-library" / "expansion-sources.json").read_text(encoding="utf-8"))
        candidate = next(
            row for row in registry["research_only_or_blocked"]
            if row["id"] == "f5tts-vietnamese-vivoice"
        )
        self.assertEqual(candidate["model_card_license"], "CC-BY-NC-SA-4.0")
        self.assertFalse(candidate["production_eligible"])

    def test_kokoro_english_preset_set_is_pinned_and_curated(self):
        sources = json.loads(SOURCES.read_text(encoding="utf-8"))
        kokoro = sources["kokoro_english"]
        self.assertEqual(kokoro["model_repo"], "hexgrad/Kokoro-82M")
        self.assertEqual(kokoro["model_revision"], "f3ff3571791e39611d31c381e3a41a3af07b4987")
        self.assertEqual(kokoro["voices_metadata_revision"], "c3327e9bac3dbe55779397bfa82de0f8806fb3bc")
        self.assertEqual(kokoro["model_file_sha256"], "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4")
        self.assertEqual(
            {voice["id"] for voice in kokoro["selected_voices"]},
            {"af_heart", "af_bella", "af_nicole", "bf_emma"},
        )
        self.assertTrue(all(voice["quality_grade"] in {"A", "A-", "B-"} for voice in kokoro["selected_voices"]))
        self.assertIn("prepare_kokoro", BUILDER.read_text(encoding="utf-8"))

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

    def test_audio_validator_accepts_extensible_pcm_wav_and_checks_subtype(self):
        script = BUILDER.read_text(encoding="utf-8")
        self.assertIn('info.format not in {"WAV", "WAVEX"}', script)
        self.assertIn('expected_subtype = {16: "PCM_16", 24: "PCM_24"}', script)
        self.assertIn("validate_audio(normalized, sample_rate, bits)", script)

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


class ExpandedProviderContractTests(unittest.TestCase):
    def test_eleven_v4_is_a_separate_high_priority_synthesis_candidate(self):
        registry = json.loads((ROOT / "voice-library" / "expansion-sources.json").read_text(encoding="utf-8"))
        candidate = next(row for row in registry["production_candidates"] if row["id"] == "elevenlabs-eleven-v4")
        self.assertEqual(candidate["model_id"], "eleven_v4")
        self.assertIn("vi", candidate["language_codes"])
        self.assertIn("en", candidate["language_codes"])
        self.assertEqual(candidate["recommended_api"], "POST /v1/text-to-dialogue")
        self.assertNotEqual(candidate["model_id"], "eleven_ttv_v3")

    def test_elevenlabs_marketplace_registry_records_separate_adoption_and_quality_signals(self):
        registry = json.loads((ROOT / "voice-library" / "expansion-sources.json").read_text(encoding="utf-8"))
        candidate = next(row for row in registry["production_candidates"] if row["id"] == "elevenlabs-shared-voice-marketplace")
        self.assertEqual(candidate["discovery_endpoint"], "GET /v1/shared-voices")
        self.assertIn("high_quality", candidate["note"])
        self.assertIn("famous", candidate["note"])
        self.assertFalse(any("celebrity" in row["id"] for row in registry["production_candidates"]))

    def test_vietnamese_voice_arena_snapshot_is_source_attributed(self):
        registry = json.loads((ROOT / "voice-library" / "expansion-sources.json").read_text(encoding="utf-8"))
        snapshot = registry["market_snapshots"]
        self.assertEqual(snapshot["source"], "https://voicearena.com/tts-leaderboard/vietnamese")
        self.assertEqual(snapshot["overall_vietnamese_top_models"][0]["model"], "Gemini 3.8 Flash-Lite TTS")
        self.assertEqual(snapshot["overall_vietnamese_top_models"][3]["model"], "Eleven v4")


    def test_google_gemini_voice_catalog_only_indexes_prebuilt_vi_en_voice_ids(self):
        registry = json.loads((ROOT / "voice-library" / "expansion-sources.json").read_text(encoding="utf-8"))
        candidate = next(row for row in registry["production_candidates"] if row["id"] == "google-gemini-prebuilt-voice-library")
        self.assertEqual(candidate["discovery_endpoint"], "GET /v1beta/voices")
        self.assertEqual(candidate["filter"], "type=prebuilt")
        self.assertEqual(candidate["language_codes"], ["vi", "en"])
        self.assertEqual(candidate["page_size_max"], 1000)
        self.assertIn("prompted and replicated", candidate["note"])


    def test_paid_eleven_v4_benchmark_is_private_confirmed_and_bounded(self):
        workflow = (ROOT / ".github" / "workflows" / "elevenlabs-v4-marketplace-benchmark.yml").read_text(encoding="utf-8")
        script = (ROOT / "scripts" / "benchmark_elevenlabs_v4_marketplace.py").read_text(encoding="utf-8")
        self.assertIn("github.event.repository.private == true", workflow)
        self.assertIn("inputs.confirm_paid_api_usage == true", workflow)
        self.assertIn("default: false", workflow)
        self.assertIn("MAX_TOTAL_REQUESTS = 8", script)
        self.assertIn("if not args.confirm_paid_api_usage", script)
        self.assertIn("do not retry until usage/history is checked", script)

    def test_gemini_voice_discovery_is_metadata_only(self):
        workflow = (ROOT / ".github" / "workflows" / "discover-gemini-prebuilt-voices.yml").read_text(encoding="utf-8")
        script = (ROOT / "scripts" / "discover_gemini_prebuilt_voices.py").read_text(encoding="utf-8")
        self.assertIn("GEMINI_API_KEY", workflow)
        self.assertIn("type=prebuilt", script)
        self.assertNotIn("/interactions", script)
        self.assertNotIn("generateContent", script)


if __name__ == "__main__":
    unittest.main()
