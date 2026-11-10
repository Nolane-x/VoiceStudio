from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "merge_elevenlabs_v4_blind_scores.py"
SPEC = importlib.util.spec_from_file_location("elevenlabs_v4_blind_score_merge", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

FIELDS = [
    "blind_sample_id", "language", "reviewer_id",
    "naturalness", "pronunciation", "prosody", "emotion", "accent_fit", "overall", "notes",
]


def write_analysis(path: Path):
    data = {
        "benchmark": "Eleven v4",
        "samples": [
            {"blind_sample_id": "sample-001", "language": "vi", "voice_id": "voice-a", "voice_name": "Voice A"},
            {"blind_sample_id": "sample-002", "language": "vi", "voice_id": "voice-b", "voice_name": "Voice B"},
            {"blind_sample_id": "sample-003", "language": "en", "voice_id": "voice-c", "voice_name": "Voice C"},
        ],
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def write_scores(path: Path, rows):
    import csv
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def score(sample_id, language, reviewer, overall, **overrides):
    row = {
        "blind_sample_id": sample_id,
        "language": language,
        "reviewer_id": reviewer,
        "naturalness": str(overrides.get("naturalness", overall)),
        "pronunciation": str(overrides.get("pronunciation", overall)),
        "prosody": str(overrides.get("prosody", overall)),
        "emotion": str(overrides.get("emotion", overall)),
        "accent_fit": str(overrides.get("accent_fit", overall)),
        "overall": str(overall),
        "notes": overrides.get("notes", ""),
    }
    return row


def test_merge_rejoins_scores_and_ranks_voices_separately_by_language(tmp_path):
    analysis = tmp_path / "analysis.json"
    scores = tmp_path / "scores.csv"
    output = tmp_path / "scored-analysis.json"
    summary = tmp_path / "rankings.csv"
    write_analysis(analysis)
    write_scores(scores, [
        score("sample-001", "vi", "listener-a", 5, notes="clear"),
        score("sample-001", "vi", "listener-b", 4),
        score("sample-002", "vi", "listener-a", 3),
        score("sample-003", "en", "listener-a", 4),
    ])

    result = MODULE.merge(analysis, scores, output, summary)

    assert result["human_review_status"] == "scored"
    assert result["human_review_summary"]["completed_sample_count"] == 3
    assert result["human_review_summary"]["review_count"] == 4
    vi = result["human_voice_rankings_by_language"]["vi"]
    assert vi[0]["voice_id"] == "voice-a"
    assert vi[0]["rank"] == 1
    assert vi[0]["average_overall"] == 4.5
    assert vi[0]["review_count"] == 2
    assert vi[1]["voice_id"] == "voice-b"
    assert output.is_file() and summary.is_file()
    assert "not standardized MOS" in result["human_review_summary"]["interpretation"]


def test_blank_template_rows_are_ignored_and_report_partial_status(tmp_path):
    analysis = tmp_path / "analysis.json"
    scores = tmp_path / "scores.csv"
    output = tmp_path / "scored-analysis.json"
    write_analysis(analysis)
    write_scores(scores, [
        score("sample-001", "vi", "listener-a", 5),
        {key: "" for key in FIELDS} | {"blind_sample_id": "sample-002", "language": "vi"},
    ])

    result = MODULE.merge(analysis, scores, output)
    assert result["human_review_status"] == "partially_scored"
    assert result["human_review_summary"]["completed_sample_count"] == 1
    assert result["samples"][1]["human_review_summary"]["status"] == "pending"


def test_unknown_sample_id_is_rejected(tmp_path):
    analysis = tmp_path / "analysis.json"
    scores = tmp_path / "scores.csv"
    write_analysis(analysis)
    write_scores(scores, [score("sample-999", "vi", "listener-a", 4)])
    try:
        MODULE.merge(analysis, scores, tmp_path / "out.json")
    except ValueError as exc:
        assert "unknown blind_sample_id" in str(exc)
    else:
        raise AssertionError("unknown blind sample was accepted")


def test_language_mismatch_is_rejected(tmp_path):
    analysis = tmp_path / "analysis.json"
    scores = tmp_path / "scores.csv"
    write_analysis(analysis)
    write_scores(scores, [score("sample-001", "en", "listener-a", 4)])
    try:
        MODULE.merge(analysis, scores, tmp_path / "out.json")
    except ValueError as exc:
        assert "language mismatch" in str(exc)
    else:
        raise AssertionError("language mismatch was accepted")


def test_duplicate_reviewer_submission_is_rejected(tmp_path):
    analysis = tmp_path / "analysis.json"
    scores = tmp_path / "scores.csv"
    write_analysis(analysis)
    row = score("sample-001", "vi", "listener-a", 4)
    write_scores(scores, [row, row])
    try:
        MODULE.merge(analysis, scores, tmp_path / "out.json")
    except ValueError as exc:
        assert "duplicate review" in str(exc)
    else:
        raise AssertionError("duplicate review was accepted")


def test_scores_outside_one_to_five_and_partial_ratings_are_rejected(tmp_path):
    analysis = tmp_path / "analysis.json"
    scores = tmp_path / "scores.csv"
    write_analysis(analysis)
    write_scores(scores, [score("sample-001", "vi", "listener-a", 6)])
    try:
        MODULE.merge(analysis, scores, tmp_path / "out.json")
    except ValueError as exc:
        assert "finite number from 1 to 5" in str(exc)
    else:
        raise AssertionError("out of range score was accepted")

    row = score("sample-001", "vi", "listener-a", 4)
    row["pronunciation"] = ""
    write_scores(scores, [row])
    try:
        MODULE.merge(analysis, scores, tmp_path / "out.json")
    except ValueError as exc:
        assert "incomplete rating row" in str(exc)
    else:
        raise AssertionError("partial rating row was accepted")


def test_review_file_must_contain_at_least_one_completed_score(tmp_path):
    analysis = tmp_path / "analysis.json"
    scores = tmp_path / "scores.csv"
    write_analysis(analysis)
    write_scores(scores, [
        {key: "" for key in FIELDS} | {"blind_sample_id": "sample-001", "language": "vi"},
    ])
    try:
        MODULE.merge(analysis, scores, tmp_path / "out.json")
    except ValueError as exc:
        assert "No completed human reviews" in str(exc)
    else:
        raise AssertionError("empty review submission was accepted")


def test_human_rankings_separate_models_even_when_voice_ids_match(tmp_path):
    analysis = tmp_path / "analysis.json"
    scores = tmp_path / "scores.csv"
    output = tmp_path / "scored-analysis.json"
    write_analysis(analysis)
    data = json.loads(analysis.read_text(encoding="utf-8"))
    data["model_id"] = "eleven_v4"
    data["samples"][0]["model_id"] = "eleven_v4"
    data["samples"][0]["voice_id"] = "Kore"
    data["samples"][1]["model_id"] = "eleven_v4"
    data["samples"][1]["voice_id"] = "Other"
    data["samples"][2]["model_id"] = "eleven_v4"
    data["samples"][2]["voice_id"] = "English"
    data["samples"].append({
        "blind_sample_id": "sample-004",
        "language": "vi",
        "voice_id": "Kore",
        "voice_name": "Kore",
        "model_id": "gemini-3.8-flash-tts",
    })
    analysis.write_text(json.dumps(data), encoding="utf-8")
    write_scores(scores, [
        score("sample-001", "vi", "listener-a", 4),
        score("sample-002", "vi", "listener-a", 3),
        score("sample-003", "en", "listener-a", 4),
        score("sample-004", "vi", "listener-a", 5),
    ])

    result = MODULE.merge(analysis, scores, output)
    vi = result["human_voice_rankings_by_language"]["vi"]
    by_model = {}
    for row in vi:
        by_model.setdefault(row["model_id"], []).append(row)
    assert set(by_model) == {"eleven_v4", "gemini-3.8-flash-tts"}
    assert by_model["eleven_v4"][0]["voice_id"] == "Kore"
    assert by_model["eleven_v4"][0]["average_overall"] == 4
    assert by_model["gemini-3.8-flash-tts"][0]["voice_id"] == "Kore"
    assert by_model["gemini-3.8-flash-tts"][0]["average_overall"] == 5
    assert by_model["eleven_v4"][0]["rank"] == 1
    assert by_model["gemini-3.8-flash-tts"][0]["rank"] == 1
    assert by_model["eleven_v4"][1]["rank"] == 2
