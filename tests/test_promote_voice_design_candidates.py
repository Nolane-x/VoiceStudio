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


def test_create_voice_uses_expected_endpoint_and_api_key_header():
    captured = {}

    def fake_open(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.method
        captured["headers"] = {k.lower(): v for k, v in request.header_items()}
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"voice_id": "persisted-voice-123"})

    result = MODULE.create_voice(_record(), "test-key", opener=fake_open)
    assert captured["url"] == MODULE.CREATE_URL
    assert captured["method"] == "POST"
    assert captured["headers"]["xi-api-key"] == "test-key"
    assert captured["body"]["generated_voice_id"] == "generated-preview-id"
    assert result["voice_id"] == "persisted-voice-123"
    assert result["shareability"] == "workspace_only_not_public_voice_library"


def test_public_repository_and_default_confirmation_gates_are_required():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.repository.private == true" in workflow
    assert "confirm_voice_creation" in workflow
    assert "secrets.ELEVENLABS_API_KEY" in workflow
    assert "default: false" in workflow
    assert "actions: read" in workflow or "permissions:" in workflow


def test_promotion_batch_is_hard_capped_at_eight():
    try:
        MODULE.select_candidates(_analysis(), {}, max_voices=9)
    except ValueError as exc:
        assert "between 1 and 8" in str(exc)
    else:
        raise AssertionError("Promotion batch must be limited to eight")
