from __future__ import annotations

import importlib.util
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_grok_tts_builtin_voices.py"
SPEC = importlib.util.spec_from_file_location("grok_tts_builtin_voice_benchmark", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_request_uses_same_four_part_corpus_for_vi_and_en():
    vi = MODULE.build_request("carina", "vi")
    en = MODULE.build_request("carina", "en")
    assert vi["voice_id"] == "carina"
    assert vi["language"] == "vi"
    assert en["language"] == "en"
    assert "[long-pause]" in vi["text"]
    assert "[long-pause]" in en["text"]
    assert len(vi["text"]) <= MODULE.MAX_REQUEST_CHARACTERS
    assert len(en["text"]) <= MODULE.MAX_REQUEST_CHARACTERS
    assert len(MODULE.SCRIPTS["vi"]) == 4
    assert len(MODULE.SCRIPTS["en"]) == 4


def test_request_rejects_unsupported_language_and_invalid_voice_ids():
    for voice_id, language in [("carina", "fr"), ("voice id with spaces", "vi"), ("../custom", "en")]:
        try:
            MODULE.build_request(voice_id, language)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid request accepted: {voice_id!r}/{language!r}")


def test_budget_ceiling_is_bounded_to_eight_requests():
    both = MODULE.estimate_max_cost_usd(2, 4)
    one = MODULE.estimate_max_cost_usd(1, 4)
    assert both == 0.36
    assert one == 0.18
    for args in [(2, 5), (0, 2), (3, 2)]:
        try:
            MODULE.estimate_max_cost_usd(*args)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid cost budget accepted: {args}")


def test_paid_generation_is_blocked_without_explicit_confirmation():
    from types import SimpleNamespace

    args = SimpleNamespace(confirm_paid_api_usage=False)
    try:
        MODULE.run(args)
    except RuntimeError as exc:
        assert "Paid xAI TTS generation blocked" in str(exc)
    else:
        raise AssertionError("paid xAI request was not blocked")


def test_generate_speech_uses_one_post_and_never_retries_ambiguous_failure(monkeypatch):
    calls = []

    def fail_once(request, timeout):
        calls.append(request)
        raise urllib.error.URLError("connection reset after submit")

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fail_once)
    try:
        MODULE.generate_speech("test-secret", "carina", "vi")
    except RuntimeError as exc:
        assert "ambiguous" in str(exc)
    else:
        raise AssertionError("network failure should fail closed")
    assert len(calls) == 1
    assert calls[0].get_method() == "POST"
    assert calls[0].get_header("Authorization") == "Bearer test-secret"


def test_voice_selection_uses_only_provider_managed_builtin_catalog_entries():
    catalog = [
        {"voice_id": "carina", "name": "Carina", "language_scope": ["vi", "en"], "kind": "provider_managed_builtin"},
        {"voice_id": "eve", "name": "Eve", "language_scope": ["vi", "en"], "kind": "provider_managed_builtin"},
    ]
    assert [row["voice_id"] for row in MODULE.select_voices(catalog, "vi", 0, 2)] == ["carina", "eve"]
    assert [row["voice_id"] for row in MODULE.select_voices(catalog, "en", 1, 1)] == ["eve"]
    try:
        MODULE.select_voices(catalog + [
            {"voice_id": "private", "name": "Private", "language_scope": ["vi"], "kind": "user_custom"}
        ], "vi", 0, 4)
    except Exception as exc:
        raise AssertionError(f"catalog selection should ignore, not break on, custom voices: {exc}")


def test_blind_gallery_exports_stable_id_without_provider_voice_identity():
    page = MODULE.make_blind_gallery([
        {
            "blind_sample_id": "sample-001",
            "language": "vi",
            "audio_file": "blind-samples/sample-001.wav",
        }
    ], ["vi"], "2026-11-01T00:00:00+00:00")
    assert 'data-sample-id="sample-001"' in page
    assert "reviewer_id" in page
    assert "card.dataset.sampleId" in page
    assert "carina" not in page
    assert "voice_id" not in page
    assert "Grok" in page


def test_blind_archive_excludes_private_analysis_mapping(tmp_path):
    import zipfile

    (tmp_path / "blind-samples").mkdir()
    (tmp_path / "blind-samples" / "sample-001.wav").write_bytes(b"audio")
    (tmp_path / "blind-review.html").write_text("Sample 001", encoding="utf-8")
    (tmp_path / "blind-review.csv").write_text("blind_sample_id\nsample-001\n", encoding="utf-8")
    (tmp_path / "BLIND-REVIEW.md").write_text("Blind listening only", encoding="utf-8")
    (tmp_path / "analysis.json").write_text('{"voice_id":"secretvoice"}', encoding="utf-8")
    archive = MODULE.create_blind_archive(tmp_path)
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert "analysis.json" not in names
        assert "blind-samples/sample-001.wav" in names
        assert all("secretvoice" not in name for name in names)


def test_workflow_requires_private_repository_and_explicit_paid_confirmation():
    workflow = (ROOT / ".github" / "workflows" / "grok-tts-builtin-benchmark.yml").read_text(encoding="utf-8")
    assert "github.event.repository.private == true" in workflow
    assert "inputs.confirm_paid_api_usage == true" in workflow
    assert "default: false" in workflow
    assert "XAI_API_KEY" in workflow
    assert "Maximum input characters" in workflow
    assert "USD {maximum_charge:.4f}" in workflow


def test_static_official_builtin_voice_catalog_has_26_distinct_profiles():
    import json

    catalog = json.loads((ROOT / "voice-library" / "grok-builtin-studio-voices.json").read_text(encoding="utf-8"))
    assert catalog["count"] == 26
    assert len(catalog["voices"]) == 26
    assert len({voice["voice_id"] for voice in catalog["voices"]}) == 26
    assert all(voice["language_scope"] == ["vi", "en"] for voice in catalog["voices"])
    assert "not popularity or quality rankings" in catalog["usage_note"].lower()
