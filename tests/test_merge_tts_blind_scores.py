from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "merge_tts_blind_scores.py"
SPEC = importlib.util.spec_from_file_location("tts_blind_score_merge", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

COLUMNS = [
    "blind_sample_id", "language", "scenario", "reviewer_id",
    "naturalness", "pronunciation", "prosody", "emotion", "notes",
]


def sample(sample_id, engine, voice, language="vi", scenario="story", rights="cleared"):
    return {
        "blind_sample_id": sample_id,
        "engine": engine,
        "engine_label": engine.title(),
        "voice_id": voice,
        "voice_label": voice.upper(),
        "language": language,
        "scenario_id": scenario,
        "scenario_title": scenario.title(),
        "rights": {
            "status": rights,
            "commercial_use": "approved" if rights == "cleared" else "not-cleared",
        },
    }


def write_manifest(path: Path):
    data = {
        "benchmark": "test benchmark",
        "sample_count": 4,
        "samples": [
            sample("sample-001", "vieneu", "adam", scenario="story"),
            sample("sample-002", "vieneu", "adam", scenario="numbers"),
            sample("sample-003", "supertonic", "M1", scenario="story", rights="manual-review-required"),
            sample("sample-004", "kokoro", "af_heart", language="en", rights="cleared"),
        ],
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def write_csv(path: Path, rows, columns=COLUMNS):
    import csv
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def score(sample_id, language, scenario, reviewer, value, **overrides):
    return {
        "blind_sample_id": sample_id,
        "language": language,
        "scenario": scenario,
        "reviewer_id": reviewer,
        "naturalness": str(overrides.get("naturalness", value)),
        "pronunciation": str(overrides.get("pronunciation", value)),
        "prosody": str(overrides.get("prosody", value)),
        "emotion": str(overrides.get("emotion", value)),
        "notes": overrides.get("notes", ""),
    }


def test_merge_ranks_voice_ids_by_language_and_separately_by_scenario(tmp_path):
    analysis, scores = tmp_path / "benchmark.json", tmp_path / "scores.csv"
    output, summary = tmp_path / "scored.json", tmp_path / "rankings.csv"
    write_manifest(analysis)
    write_csv(scores, [
        score("sample-001", "vi", "story", "listener-a", 5),
        score("sample-001", "vi", "story", "listener-b", 4),
        score("sample-002", "vi", "numbers", "listener-a", 3),
        score("sample-003", "vi", "story", "listener-a", 2),
        score("sample-004", "en", "story", "listener-a", 4),
    ])

    result = MODULE.merge(analysis, scores, output, summary)

    assert result["human_review_status"] == "scored"
    assert result["human_review_summary"]["completed_sample_count"] == 4
    assert result["human_review_summary"]["review_count"] == 5
    vi = result["voice_rankings_by_language"]["vi"]
    assert vi[0]["engine"] == "vieneu"
    assert vi[0]["voice_id"] == "adam"
    assert vi[0]["average_overall"] == 4.0
    assert vi[0]["review_count"] == 3
    assert vi[1]["rights_status"] == "manual-review-required"
    assert result["voice_rankings_by_language"]["en"][0]["voice_id"] == "af_heart"
    assert len(result["voice_rankings_by_language_and_scenario"]["vi"]) == 2
    assert summary.is_file()


def test_legacy_score_csv_without_reviewer_column_defaults_to_reviewer_one(tmp_path):
    analysis, scores = tmp_path / "benchmark.json", tmp_path / "scores.csv"
    write_manifest(analysis)
    columns = [column for column in COLUMNS if column != "reviewer_id"]
    row = score("sample-001", "vi", "story", "ignored", 5)
    row.pop("reviewer_id")
    write_csv(scores, [row], columns=columns)
    result = MODULE.merge(analysis, scores, tmp_path / "scored.json")
    assert result["samples"][0]["human_reviews"][0]["reviewer_id"] == "reviewer-1"
    assert result["human_review_status"] == "partially_scored"


def test_blank_template_rows_are_ignored(tmp_path):
    analysis, scores = tmp_path / "benchmark.json", tmp_path / "scores.csv"
    write_manifest(analysis)
    blank = {column: "" for column in COLUMNS}
    blank.update({"blind_sample_id": "sample-001", "language": "vi", "scenario": "story"})
    write_csv(scores, [blank])
    try:
        MODULE.merge(analysis, scores, tmp_path / "scored.json")
    except ValueError as exc:
        assert "No completed human reviews" in str(exc)
    else:
        raise AssertionError("blank-only review file should not pass")


def test_unknown_blind_sample_is_rejected(tmp_path):
    analysis, scores = tmp_path / "benchmark.json", tmp_path / "scores.csv"
    write_manifest(analysis)
    write_csv(scores, [score("sample-999", "vi", "story", "listener", 4)])
    try:
        MODULE.merge(analysis, scores, tmp_path / "scored.json")
    except ValueError as exc:
        assert "unknown blind_sample_id" in str(exc)
    else:
        raise AssertionError("unknown blind sample was accepted")


def test_language_or_scenario_mismatch_is_rejected(tmp_path):
    analysis, scores = tmp_path / "benchmark.json", tmp_path / "scores.csv"
    write_manifest(analysis)
    write_csv(scores, [score("sample-001", "en", "story", "listener", 4)])
    try:
        MODULE.merge(analysis, scores, tmp_path / "out.json")
    except ValueError as exc:
        assert "language mismatch" in str(exc)
    else:
        raise AssertionError("language mismatch was accepted")

    write_csv(scores, [score("sample-001", "vi", "longform", "listener", 4)])
    try:
        MODULE.merge(analysis, scores, tmp_path / "out.json")
    except ValueError as exc:
        assert "scenario mismatch" in str(exc)
    else:
        raise AssertionError("scenario mismatch was accepted")


def test_duplicate_reviewer_submission_is_rejected(tmp_path):
    analysis, scores = tmp_path / "benchmark.json", tmp_path / "scores.csv"
    write_manifest(analysis)
    row = score("sample-001", "vi", "story", "listener-a", 4)
    write_csv(scores, [row, row])
    try:
        MODULE.merge(analysis, scores, tmp_path / "out.json")
    except ValueError as exc:
        assert "duplicate review" in str(exc)
    else:
        raise AssertionError("duplicate reviewer score was accepted")


def test_scores_must_be_complete_and_in_range(tmp_path):
    analysis, scores = tmp_path / "benchmark.json", tmp_path / "scores.csv"
    write_manifest(analysis)
    row = score("sample-001", "vi", "story", "listener-a", 6)
    write_csv(scores, [row])
    try:
        MODULE.merge(analysis, scores, tmp_path / "out.json")
    except ValueError as exc:
        assert "finite number from 1 to 5" in str(exc)
    else:
        raise AssertionError("out of range score was accepted")

    row = score("sample-001", "vi", "story", "listener-a", 4)
    row["emotion"] = ""
    write_csv(scores, [row])
    try:
        MODULE.merge(analysis, scores, tmp_path / "out.json")
    except ValueError as exc:
        assert "incomplete rating row" in str(exc)
    else:
        raise AssertionError("incomplete score was accepted")


def test_high_human_score_does_not_clear_unapproved_usage_rights(tmp_path):
    analysis, scores = tmp_path / "benchmark.json", tmp_path / "scores.csv"
    write_manifest(analysis)
    write_csv(scores, [score("sample-003", "vi", "story", "listener-a", 5)])
    result = MODULE.merge(analysis, scores, tmp_path / "scored.json")
    row = result["voice_rankings_by_language"]["vi"][0]
    assert row["engine"] == "supertonic"
    assert row["average_overall"] == 5
    assert row["rights_status"] == "manual-review-required"
    assert row["commercial_use"] == "not-cleared"
    assert "independent production gate" in result["human_review_summary"]["interpretation"]
