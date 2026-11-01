from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_voice_contribution.py"
SCHEMA_PATH = ROOT / "voice-library" / "voice-contribution.schema.json"
SPEC = importlib.util.spec_from_file_location("voice_contribution_validator", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def valid_manifest():
    return {
        "schema_version": 1,
        "contribution_id": "e0e2a7f8-5029-49ab-85d5-bdcb9c887b20",
        "contributor_ref": "vc_0123456789abcdef",
        "display_name": "Northern Vietnamese warm narrator 01",
        "sample_asset_ref": "asset_0123456789abcdefghijkl",
        "speaker_is_contributor": True,
        "adult_attested": True,
        "privacy_notice_acknowledged": True,
        "voice_description": "Warm, measured northern Vietnamese narration.",
        "languages": [
            {
                "language": "vi",
                "locale": "vi-VN",
                "accent": "Northern Vietnamese",
                "persona_tags": ["narration", "warm"],
                "native_language_review_required": True,
            },
            {
                "language": "en",
                "locale": "en-US",
                "accent": "General American",
                "persona_tags": ["narration"],
                "native_language_review_required": True,
            },
        ],
        "consent": {
            "consent_version": "voice-consent-v1",
            "signed_at": "2026-11-01T12:00:00Z",
            "private_record_ref": "vault_0123456789abcdefghijkl",
            "record_sha256": "a" * 64,
            "disclosure_acknowledged": True,
            "rights_granted": ["tts_synthesis", "voice_replication", "commercial_use"],
            "rights_not_granted": ["public_preview", "public_distribution", "model_training", "derivative_voice_generation"],
            "withdrawal_route_ref": "vault_abcdef0123456789abcdef01",
        },
        "provenance": {
            "recording_origin": "self_recorded_by_contributor",
            "speaker_identity_confirmed": True,
            "recording_rights_ref": "vault_abcdef0123456789abcdef01",
        },
        "rights_review": {"status": "pending"},
        "quality_review": {
            "status": "pending",
            "native_language_review": False,
            "pronunciation_review": False,
            "longform_stability_review": False,
        },
        "production_ready": False,
    }


def write_manifest(tmp_path: Path, manifest: dict) -> Path:
    path = tmp_path / "contribution.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_pending_pseudonymous_contribution_is_schema_valid(tmp_path):
    path = write_manifest(tmp_path, valid_manifest())
    assert MODULE.validate_manifest(path, SCHEMA) == []


def test_production_ready_requires_granted_rights_approved_reviews_and_mature_consent(tmp_path):
    manifest = valid_manifest()
    manifest["consent"]["rights_granted"] = [
        "tts_synthesis", "voice_replication", "commercial_use",
    ]
    manifest["rights_review"] = {
        "status": "approved",
        "reviewer_ref": "reviewer_0123456789ab",
        "reviewed_at": "2026-11-01T12:00:00Z",
    }
    manifest["quality_review"] = {
        "status": "approved",
        "native_language_review": True,
        "pronunciation_review": True,
        "longform_stability_review": True,
        "blind_review_id": "review_0123456789ab",
        "reviewed_at": "2026-11-01T12:00:00Z",
    }
    manifest["production_ready"] = True
    assert MODULE.validate_manifest(write_manifest(tmp_path, manifest), SCHEMA) == []


def test_minor_or_non_contributor_speaker_is_rejected(tmp_path):
    manifest = valid_manifest()
    manifest["adult_attested"] = False
    issues = MODULE.validate_manifest(write_manifest(tmp_path, manifest), SCHEMA)
    assert any("True was expected" in issue for issue in issues)

    manifest = valid_manifest()
    manifest["speaker_is_contributor"] = False
    issues = MODULE.validate_manifest(write_manifest(tmp_path, manifest), SCHEMA)
    assert any("True was expected" in issue for issue in issues)


def test_public_manifest_rejects_personal_information_and_audio_urls(tmp_path):
    manifest = valid_manifest()
    manifest["email"] = "person@example.com"
    issues = MODULE.validate_manifest(write_manifest(tmp_path, manifest), SCHEMA)
    assert any("Additional properties are not allowed" in issue for issue in issues)

    manifest = valid_manifest()
    manifest["sample_asset_ref"] = "https://example.com/raw-voice.wav"
    issues = MODULE.validate_manifest(write_manifest(tmp_path, manifest), SCHEMA)
    assert issues


def test_rights_cannot_be_both_granted_and_denied(tmp_path):
    manifest = valid_manifest()
    manifest["consent"]["rights_granted"].append("model_training")
    issues = MODULE.validate_manifest(write_manifest(tmp_path, manifest), SCHEMA)
    assert any("both granted and denied" in issue for issue in issues)


def test_production_ready_requires_explicit_commercial_and_replication_permissions(tmp_path):
    manifest = valid_manifest()
    manifest["production_ready"] = True
    manifest["rights_review"] = {"status": "approved"}
    manifest["quality_review"] = {
        "status": "approved",
        "native_language_review": True,
        "pronunciation_review": True,
        "longform_stability_review": True,
    }
    issues = MODULE.validate_manifest(write_manifest(tmp_path, manifest), SCHEMA)
    assert any("commercial_use" in issue for issue in issues)
    assert any("voice_replication" in issue for issue in issues)


def test_public_preview_requires_explicit_distribution_permission(tmp_path):
    manifest = valid_manifest()
    manifest["consent"]["rights_granted"].append("public_preview")
    issues = MODULE.validate_manifest(write_manifest(tmp_path, manifest), SCHEMA)
    assert any("public_preview requires public_distribution" in issue for issue in issues)


def test_approved_quality_state_requires_all_three_review_checks(tmp_path):
    manifest = valid_manifest()
    manifest["quality_review"]["status"] = "approved"
    issues = MODULE.validate_manifest(write_manifest(tmp_path, manifest), SCHEMA)
    assert any("all checks pass" in issue for issue in issues)


def test_contribution_directory_can_be_empty_without_creating_a_fake_voice(tmp_path):
    assert MODULE.collect_paths(tmp_path) == []
