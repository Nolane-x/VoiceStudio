#!/usr/bin/env python3
"""Reattach blind listening scores to the private Eleven v4 analysis mapping.

The input scores are exported from blind-review.html. This tool validates
reviewer/sample/language identity, rejects duplicate and out-of-range scores,
and emits per-language human preference summaries without calling any API.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

RATING_FIELDS = (
    "naturalness", "pronunciation", "prosody", "emotion", "accent_fit", "overall",
)
CSV_FIELDS = (
    "blind_sample_id", "language", "reviewer_id",
    *RATING_FIELDS, "notes",
)


def read_scores(path: Path, sample_map: dict[str, dict]) -> dict[str, list[dict]]:
    reviews: dict[str, list[dict]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(CSV_FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Score CSV is missing columns: {', '.join(sorted(missing))}")
        for line_number, raw in enumerate(reader, start=2):
            sample_id = (raw.get("blind_sample_id") or "").strip()
            language = (raw.get("language") or "").strip().lower()
            reviewer = (raw.get("reviewer_id") or "reviewer-1").strip()[:32] or "reviewer-1"
            if not sample_id:
                raise ValueError(f"Line {line_number}: blind_sample_id is required")
            sample = sample_map.get(sample_id)
            if sample is None:
                raise ValueError(f"Line {line_number}: unknown blind_sample_id {sample_id!r}")
            if language != sample.get("language"):
                raise ValueError(
                    f"Line {line_number}: language mismatch for {sample_id}: "
                    f"{language!r} != {sample.get('language')!r}"
                )
            values = {field: (raw.get(field) or "").strip() for field in RATING_FIELDS}
            if not any(values.values()):
                # Untouched template row: no review submitted for this sample.
                continue
            if any(not value for value in values.values()):
                missing_ratings = [key for key, value in values.items() if not value]
                raise ValueError(
                    f"Line {line_number}: incomplete rating row; missing {', '.join(missing_ratings)}"
                )
            pair = (sample_id, reviewer)
            if pair in seen:
                raise ValueError(
                    f"Line {line_number}: duplicate review for {sample_id} by {reviewer}"
                )
            seen.add(pair)
            numeric = {}
            for field, value in values.items():
                try:
                    score = float(value)
                except ValueError as exc:
                    raise ValueError(f"Line {line_number}: {field} must be a number from 1 to 5") from exc
                if not math.isfinite(score) or not 1 <= score <= 5:
                    raise ValueError(f"Line {line_number}: {field} must be a finite number from 1 to 5")
                numeric[field] = score
            reviews[sample_id].append({
                "reviewer_id": reviewer,
                **numeric,
                "notes": (raw.get("notes") or "").strip()[:2000],
            })
    if not any(reviews.values()):
        raise ValueError("No completed human reviews were found in the score CSV")
    return reviews


def summarize(analysis: dict, reviews: dict[str, list[dict]]) -> dict:
    samples = analysis.get("samples")
    if not isinstance(samples, list):
        raise ValueError("Analysis manifest must contain a samples list")
    sample_map = {}
    for sample in samples:
        sample_id = sample.get("blind_sample_id")
        if not isinstance(sample_id, str) or not sample_id:
            raise ValueError("Every analysis sample must have a blind_sample_id")
        if sample_id in sample_map:
            raise ValueError(f"Analysis manifest contains duplicate sample ID {sample_id}")
        sample_map[sample_id] = sample

    # Validate before mutating the analysis object.
    attached = read_scores(Path(args_scores_placeholder), sample_map) if False else reviews
    voice_buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for sample in samples:
        sample_reviews = attached.get(sample["blind_sample_id"], [])
        sample["human_reviews"] = sample_reviews
        if sample_reviews:
            sample["human_review_summary"] = {
                "review_count": len(sample_reviews),
                **{
                    field: round(sum(row[field] for row in sample_reviews) / len(sample_reviews), 4)
                    for field in RATING_FIELDS
                },
            }
            voice_buckets[(sample.get("language", ""), sample.get("voice_id", ""))].append(
                sample["human_review_summary"]
            )
        else:
            sample["human_review_summary"] = {"review_count": 0, "status": "pending"}

    rankings = []
    for (language, voice_id), rows in voice_buckets.items():
        if not voice_id:
            continue
        count = sum(row["review_count"] for row in rows)
        summary = {
            "language": language,
            "voice_id": voice_id,
            "voice_name": next(
                sample.get("voice_name", voice_id)
                for sample in samples
                if sample.get("language") == language and sample.get("voice_id") == voice_id
            ),
            "sample_count": len(rows),
            "review_count": count,
        }
        for field in RATING_FIELDS:
            weighted = sum(row[field] * row["review_count"] for row in rows)
            summary[f"average_{field}"] = round(weighted / count, 4)
        rankings.append(summary)
    rankings.sort(key=lambda row: (row["language"], -row["average_overall"], row["voice_name"].casefold()))

    by_language: dict[str, list[dict]] = defaultdict(list)
    for row in rankings:
        by_language[row["language"]].append(row)
    language_rankings = {}
    for language, rows in by_language.items():
        language_rankings[language] = [
            {**row, "rank": rank}
            for rank, row in enumerate(rows, start=1)
        ]

    output = dict(analysis)
    output["human_review_status"] = "scored" if all(
        sample["human_review_summary"]["review_count"] > 0 for sample in samples
    ) else "partially_scored"
    output["human_review_summary"] = {
        "completed_sample_count": sum(
            1 for sample in samples if sample["human_review_summary"]["review_count"] > 0
        ),
        "total_sample_count": len(samples),
        "review_count": sum(len(rows) for rows in attached.values()),
        "rating_scale": "1 (poor) to 5 (excellent)",
        "interpretation": (
            "Human listening preference scores for this blind review cohort only; "
            "not standardized MOS, a universal quality measure, or a license/rights clearance."
        ),
    }
    output["human_voice_rankings_by_language"] = language_rankings
    return output


def merge(analysis_path: Path, scores_path: Path, output_path: Path, csv_path: Path | None = None) -> dict:
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    if not isinstance(analysis, dict):
        raise ValueError("Analysis manifest must be a JSON object")
    samples = analysis.get("samples")
    if not isinstance(samples, list):
        raise ValueError("Analysis manifest must contain a samples list")
    sample_map = {}
    for sample in samples:
        sample_id = sample.get("blind_sample_id")
        if not isinstance(sample_id, str) or not sample_id or sample_id in sample_map:
            raise ValueError("Analysis manifest has a missing or duplicate blind_sample_id")
        sample_map[sample_id] = sample
    reviews = read_scores(scores_path, sample_map)
    result = summarize(analysis, reviews)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if csv_path:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            row
            for language in sorted(result["human_voice_rankings_by_language"])
            for row in result["human_voice_rankings_by_language"][language]
        ]
        fields = [
            "language", "rank", "voice_name", "voice_id", "sample_count", "review_count",
            *[f"average_{field}" for field in RATING_FIELDS],
        ]
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    return result


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", required=True, type=Path)
    parser.add_argument("--scores", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--summary-csv", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = merge(args.analysis, args.scores, args.output, args.summary_csv)
    except Exception as exc:
        print(f"[eleven-v4-score-merge] ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        f"[eleven-v4-score-merge] COMPLETE {result['human_review_summary']['completed_sample_count']}/"
        f"{result['human_review_summary']['total_sample_count']} samples; "
        f"{result['human_review_summary']['review_count']} reviews; "
        f"rankings for {len(result['human_voice_rankings_by_language'])} languages",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
