from __future__ import annotations

import base64
import csv
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "promote_voice_design_candidates.py"
WORKFLOW = ROOT / ".github" / "workflows" / "promote-voice-design-candidates.yml"
SPEC = importlib.util.spec_from_file_location("promote_voice_design_candidates", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _record(blind_id="candidate-001"):
    return {
        "blind_sample_id": blind_id,
        "profile_id": "vi-north-hanoi-0001",
        "generated_voice_id": "generated-preview-id",
        "language": "vi",
        "locale": "vi-VN",
        "accent_id": "north-hanoi",
        "intended_use_case": "documentary",
        "market_archetype_id": "cinematic-documentary",
        "dimensions": {"use_case": "documentary"},
        "voice_description": (
            "Create an original Vietnamese synthetic narrator. Use a natural Northern accent, "
            "warm timbre and measured pacing. Preserve all six tones. Do not imitate any real person."
        ),
        "shareability": "not_shareable_to_public_elevenlabs_voice_library",
        "generation_state": "preview_generated_not_saved_as_persistent_voice",
        "human_review": {
            "approved": True,
            "scores": {
                "naturalness": 5, "pronunciation": 5, "accent_fit": 5,
                "prosody": 4, "distinctiveness": 4, "overall": 5
            },
            "notes": "Approved by human listener",
        },
    }


def _analysis():
    return {
        "provider": "ElevenLabs Voice Design",
        "records": [_record()],
    }


def _rating(approve="yes", **scores):
    row = {
        "blind_sample_id": "candidate-001",
        "language": "VI",
        "approve": approve,
        "naturalness": "5",
        "pronunciation": "5",
        "accent_fit": "5",
        "prosody": "4",
        "distinctiveness": "4",
        "overall": "5",
        "notes": "Clear and natural",
    }
    row.update(scores)
    return row


def test_select_candidates_requires_explicit_approval_and_all_thresholds():
    analysis = _analysis()
    selected = MODULE.select_candidates(analysis, {
        "candidate-001": {**_rating(), "approved": True, "scores": {
            "naturalness": 5, "pronunciation": 5, "accent_fit": 5,
            "prosody": 4, "distinctiveness": 4, "overall": 5
        }, "notes": ""},
    })
    assert [x["blind_sample_id"] for x in selected] == ["candidate-001"]

    unapproved = MODULE.select_candidates(analysis, {
        "candidate-001": {**_rating("no"), "approved": False, "scores": {}, "notes": ""},
    })
    assert unapproved == []

    low = MODULE.select_candidates(analysis, {
        "candidate-001": {"approved": True, "scores": {
            "naturalness": 3, "pronunciation": 5, "accent_fit": 5,
            "prosody": 4, "distinctiveness": 4, "overall": 5
        }, "notes": ""},
    })
    assert low == []


def test_human_csv_requires_approve_and_score_columns(tmp_path):
    path = tmp_path / "review.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "blind_sample_id", "language", "approve", *MODULE.SCORE_FIELDS, "notes"
        ])
        writer.writeheader()
        writer.writerow(_rating())
    rows = MODULE.load_ratings(path)
    assert rows["candidate-001"]["approved"] is True
    assert rows["candidate-001"]["scores"]["overall"] == 5.0


def test_unknown_duplicate_and_invalid_rating_rows_are_rejected(tmp_path):
    path = tmp_path / "review.csv"
    fields = ["blind_sample_id", "language", "approve", *MODULE.SCORE_FIELDS, "notes"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerow(_rating())
        writer.writerow(_rating())
    try:
        MODULE.load_ratings(path)
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("Duplicate blind IDs must be rejected")

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerow(_rating(overall="9"))
    try:
        MODULE.load_ratings(path)
    except ValueError as exc:
        assert "between 1 and 5" in str(exc)
    else:
        raise AssertionError("Out-of-range scores must be rejected")


def test_payload_creates_account_voice_without_publication():
    payload = MODULE.build_voice_payload(_record())
    assert payload["generated_voice_id"] == "generated-preview-id"
    assert payload["voice_name"].startswith("VS-VI-")
    assert payload["labels"]["review"] == "human-approved"
    assert "celebrity" not in payload["voice_name"].lower()


def test_payload_refuses_to_create_a_voice_without_human_approval_and_qualified_scores():
    record = _record()
    record.pop("human_review")
    try:
        MODULE.build_voice_payload(record)
    except ValueError as exc:
        assert "explicit human approval" in str(exc)
    else:
        raise AssertionError("Promotion without explicit approval must be blocked")

    record = _record()
    record["human_review"]["approved"] = False
    try:
        MODULE.build_voice_payload(record)
    except ValueError as exc:
        assert "explicit human approval" in str(exc)
    else:
        raise AssertionError("Unapproved preview must never be promoted")

    record = _record()
    record["human_review"]["scores"]["pronunciation"] = 3
    try:
        MODULE.build_voice_payload(record)
    except ValueError as exc:
        assert "do not meet promotion thresholds" in str(exc)
    else:
        raise AssertionError("Low pronunciation scores must block promotion")


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_create_voice_searches_account_before_post_and_tags_generated_preview_id():
    captured = []

    def fake_open(request, timeout):
        captured.append({
            "url": request.full_url,
            "method": request.method,
            "headers": {k.lower(): v for k, v in request.header_items()},
            "body": json.loads(request.data.decode("utf-8")) if request.data else None,
        })
        if request.method == "GET":
            return _FakeResponse({"voices": [], "has_more": False, "next_page_token": None})
        return _FakeResponse({"voice_id": "persisted-voice-123", "name": "VS-VI-north-hanoi-001"})

    result = MODULE.create_voice(_record(), "test-key", opener=fake_open)
    assert len(captured) == 2
    assert captured[0]["url"].startswith(MODULE.LIST_VOICES_URL + "?")
    assert "voice_type=non-community" in captured[0]["url"]
    assert captured[0]["method"] == "GET"
    assert captured[0]["headers"]["xi-api-key"] == "test-key"
    assert captured[1]["url"] == MODULE.CREATE_URL
    assert captured[1]["method"] == "POST"
    assert captured[1]["headers"]["xi-api-key"] == "test-key"
    assert captured[1]["body"]["generated_voice_id"] == "generated-preview-id"
    assert captured[1]["body"]["labels"][MODULE.PROMOTION_MARKER_LABEL] == "generated-preview-id"
    assert result["voice_id"] == "persisted-voice-123"
    assert result["generated_voice_id"] == "generated-preview-id"
    assert result["shareability"] == "workspace_only_not_public_voice_library"


def test_existing_matching_voice_is_reconciled_without_duplicate_post():
    post_count = 0

    def fake_open(request, timeout):
        nonlocal post_count
        if request.method == "GET":
            return _FakeResponse({
                "voices": [{
                    "voice_id": "already-created",
                    "name": "VS-VI-north-hanoi-001",
                    "labels": {MODULE.PROMOTION_MARKER_LABEL: "generated-preview-id"},
                }],
                "has_more": False,
                "next_page_token": None,
            })
        post_count += 1
        return _FakeResponse({"voice_id": "duplicate-should-not-exist"})

    result = MODULE.create_voice(_record(), "test-key", opener=fake_open)
    assert result["voice_id"] == "already-created"
    assert result["reconciled_existing"] is True
    assert post_count == 0


def test_ambiguous_post_records_unknown_after_reconciliation_finds_no_voice():
    import urllib.error

    calls = {"get": 0, "post": 0}

    def fake_open(request, timeout):
        if request.method == "GET":
            calls["get"] += 1
            return _FakeResponse({"voices": [], "has_more": False, "next_page_token": None})
        calls["post"] += 1
        raise urllib.error.URLError("connection dropped after server accepted request")

    try:
        MODULE.create_voice(_record(), "test-key", opener=fake_open, sleep=lambda _delay: None)
    except MODULE.VoiceCreationOutcomeUnknown:
        pass
    else:
        raise AssertionError("An ambiguous create response must never be called a definite failure")
    assert calls["post"] == 1
    assert calls["get"] == 4  # initial preflight plus three reconciliation reads


def test_unknown_ledger_is_not_counted_as_completed():
    ledger = {
        "records": [
            {"blind_sample_id": "candidate-001", "status": "created"},
            {"blind_sample_id": "candidate-002", "status": "unknown", "generated_voice_id": "generated-002"},
        ],
    }
    MODULE._refresh_ledger_counts(ledger)
    assert ledger["created_count"] == 1
    assert ledger["unknown_count"] == 1
    assert ledger["completed"] is False


def test_previous_unknown_ledger_requires_manual_confirmation_before_post(tmp_path):
    previous_path = tmp_path / "previous-ledger.json"
    previous = {
        "provider": "ElevenLabs",
        "operation": "create_voice_from_existing_voice_design_preview",
        "source_run_id": "41234567890",
        "records": [{
            "blind_sample_id": "candidate-001",
            "generated_voice_id": "generated-preview-id",
            "status": "unknown",
            "error": "connection lost",
        }],
    }
    previous_path.write_text(json.dumps(previous), encoding="utf-8")
    loaded = MODULE.load_previous_ledger(previous_path, "41234567890")
    assert loaded["records"][0]["status"] == "unknown"


def test_public_repository_and_default_confirmation_gates_are_required():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.repository.private == true" in workflow
    assert "confirm_voice_creation" in workflow
    assert "secrets.ELEVENLABS_API_KEY" in workflow
    assert "default: false" in workflow
    assert "actions: read" in workflow or "permissions:" in workflow
    assert "previous_ledger_run_id" in workflow
    assert "actions/download-artifact@" in workflow
    assert "run-id: ${{ inputs.previous_ledger_run_id }}" in workflow
    assert "confirm_retry_unknown" in workflow
    assert "confirm-retry-unknown" in workflow


def test_promotion_batch_is_hard_capped_at_eight():
    try:
        MODULE.select_candidates(_analysis(), {}, max_voices=9)
    except ValueError as exc:
        assert "between 1 and 8" in str(exc)
    else:
        raise AssertionError("Promotion batch must be limited to eight")


def test_default_retry_sleep_dependency_is_importable():
    # create_voice binds time.sleep as a default argument during module import.
    assert callable(MODULE.time.sleep)
