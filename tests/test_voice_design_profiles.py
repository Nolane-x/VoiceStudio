from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate_voice_design_profiles.py"
SCHEMA_PATH = ROOT / "voice-library" / "voice-design-profile.schema.json"
SPEC = importlib.util.spec_from_file_location("generate_voice_design_profiles", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_catalog_creates_one_thousand_original_profiles_per_language(tmp_path):
    manifest = MODULE.write_catalog(tmp_path, "both", 1000)
    rows = [json.loads(line) for line in (tmp_path / "profiles.jsonl").read_text(encoding="utf-8").splitlines()]
    assert manifest["total_profiles"] == 2000
    assert manifest["profiles_by_language"] == {"vi": 1000, "en": 1000}
    assert len(rows) == 2000
    assert manifest["unique_rendered_voice_identities"] == 0
    assert manifest["is_rendered_voice_catalog"] is False
    assert manifest["paid_api_calls_performed"] == 0


def test_profile_ids_seeds_and_design_combinations_are_unique():
    for language in ("vi", "en"):
        rows = MODULE.build_profiles(language, 1000)
        assert len({row["profile_id"] for row in rows}) == 1000
        assert len({row["seed"] for row in rows}) == 1000
        signatures = {
            (row["accent_id"], tuple(sorted(row["dimensions"].items())))
            for row in rows
        }
        assert len(signatures) == 1000


def test_profiles_conform_to_published_json_schema():
    import jsonschema

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for language in ("vi", "en"):
        for profile in MODULE.build_profiles(language, 1000):
            validator.validate(profile)


def test_profiles_match_provider_field_length_constraints_and_originality_rules():
    for language in ("vi", "en"):
        rows = MODULE.build_profiles(language, 32)
        for row in rows:
            assert 20 <= len(row["voice_description"]) <= 1000
            assert 100 <= len(row["preview_text"]) <= 1000
            assert "Do not imitate" in row["voice_description"]
            assert row["identity_class"] == "original_synthetic_persona"
            assert row["generation_state"] == "blueprint_only_not_a_rendered_voice"
            assert row["shareability"] == "not_shareable_to_public_elevenlabs_voice_library"


def test_catalog_generation_is_deterministic():
    a = MODULE.build_profiles("vi", 16)
    b = MODULE.build_profiles("vi", 16)
    assert a == b
    canonical = "\n".join(json.dumps(row, sort_keys=True) for row in a).encode()
    assert hashlib.sha256(canonical).hexdigest() == hashlib.sha256(
        "\n".join(json.dumps(row, sort_keys=True) for row in b).encode()
    ).hexdigest()


def test_accent_families_are_present_in_large_catalog():
    vi = MODULE.build_profiles("vi", 1000)
    en = MODULE.build_profiles("en", 1000)
    assert {row["accent_id"] for row in vi} == {row[0] for row in MODULE.ACCENTS["vi"]}
    assert {row["accent_id"] for row in en} == {row[0] for row in MODULE.ACCENTS["en"]}
    assert len({row["dimensions"]["use_case"] for row in vi}) == len(MODULE.DIMENSIONS["use_case"])
    assert len({row["dimensions"]["timbre"] for row in en}) == len(MODULE.DIMENSIONS["timbre"])
