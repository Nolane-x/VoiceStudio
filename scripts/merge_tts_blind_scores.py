#!/usr/bin/env python3
"""Merge blind TTS listening scores with the private benchmark manifest.

The shareable listening CSV contains only blind sample IDs and human ratings.
This tool joins those ratings to engine/voice metadata after listening, ranks
candidates separately for Vietnamese and English, and keeps rights status as an
independent gate. It never generates audio or calls a provider API.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

RATING_FIELDS = ("naturalness", "pronunciation", "prosody", "emotion")
REQUIRED_COLUMNS = ("blind_sample_id", "language", "scenario", *RATING_FIELDS)
CSV_OUTPUT_FIELDS = (
    "language", "rank", "engine", "engine_label", "voice_id", "voice_label",
    "scenario", "sample_count", "review_count", "average_overall",
    "average_naturalness", "average_pronunciation", "average_prosody",
    "average_emotion", "rights_status", "commercial_use",
)


def _load_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("samples"), list):
        raise ValueError("Benchmark manifest must be a JSON object with a samples list")
    return value


def _index_samples(manifest: dict[str, Any]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for position, sample in enumerate(manifest["samples"], start=1):
        if not isinstance(sample, dict):
            raise ValueError(f"Manifest sample {position} is not an object")
        sample_id = sample.get("blind_sample_id")
        if not isinstance(sample_id, str) or not sample_id.strip():
            raise ValueError(f"Manifest sample {position} has no blind_sample_id")
        if sample_id in index:
            raise ValueError(f"Manifest contains duplicate blind_sample_id {sample_id!r}")
        language = sample.get("language")
        scenario = sample.get("scenario_id")
        engine = sample.get("engine")
        voice_id = sample.get("voice_id")
        if language not in {"vi", "en"}:
            raise ValueError(f"Manifest sample {sample_id} has unsupported language {language!r}")
        if not isinstance(scenario, str) or not scenario:
            raise ValueError(f"Manifest sample {sample_id} has no scenario_id")
        if not isinstance(engine, str) or not engine:
            raise ValueError(f"Manifest sample {sample_id} has no engine")
        if not isinstance(voice_id, str) or not voice_id:
            raise ValueError(f"Manifest sample {sample_id} has no voice_id")
        index[sample_id] = sample
    return index


def read_scores(path: Path, sample_index: dict[str, dict]) -> dict[str, list[dict]]:
    by_sample: dict[str, list[dict]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = set(REQUIRED_COLUMNS) - columns
        if missing:
            raise ValueError(f"Score CSV is missing columns: {', '.join(sorted(missing))}")

        for line_number, raw in enumerate(reader, start=2):
            sample_id = (raw.get("blind_sample_id") or "").strip()
            language = (raw.get("language") or "").strip().lower()
            scenario = (raw.get("scenario") or "").strip()
            reviewer = (raw.get("reviewer_id") or "reviewer-1").strip()[:32] or "reviewer-1"
            if not sample_id:
                raise ValueError(f"Line {line_number}: blind_sample_id is required")
            sample = sample_index.get(sample_id)
            if sample is None:
                raise ValueError(f"Line {line_number}: unknown blind_sample_id {sample_id!r}")
            if language != sample["language"]:
                raise ValueError(
                    f"Line {line_number}: language mismatch for {sample_id}: "
                    f"{language!r} != {sample['language']!r}"
                )
            if scenario != sample["scenario_id"]:
                raise ValueError(
                    f"Line {line_number}: scenario mismatch for {sample_id}: "
                    f"{scenario!r} != {sample['scenario_id']!r}"
                )

            values = {field: (raw.get(field) or "").strip() for field in RATING_FIELDS}
            if not any(values.values()):
                # An untouched template row has no submitted rating.
                continue
            if any(not value for value in values.values()):
                missing_ratings = [field for field, value in values.items() if not value]
                raise ValueError(
                    f"Line {line_number}: incomplete rating row; missing {', '.join(missing_ratings)}"
                )

            pair = (sample_id, reviewer)
            if pair in seen:
                raise ValueError(
                    f"Line {line_number}: duplicate review for {sample_id} by {reviewer}"
                )
            seen.add(pair)

            numeric: dict[str, float] = {}
            for field, value in values.items():
                try:
                    score = float(value)
                except ValueError as exc:
                    raise ValueError(
                        f"Line {line_number}: {field} must be a number from 1 to 5"
                    ) from exc
                if not math.isfinite(score) or not 1 <= score <= 5:
                    raise ValueError(
                        f"Line {line_number}: {field} must be a finite number from 1 to 5"
                    )
                numeric[field] = score

            by_sample[sample_id].append({
                "reviewer_id": reviewer,
                **numeric,
                "notes": (raw.get("notes") or "").strip()[:2000],
            })

    if not any(by_sample.values()):
        raise ValueError("No completed human reviews were found in the score CSV")
    return by_sample


def _average_reviews(reviews: list[dict]) -> dict:
    count = len(reviews)
    result = {
        "review_count": count,
        "average_overall": round(
            sum(sum(row[field] for field in RATING_FIELDS) / len(RATING_FIELDS) for row in reviews) / count,
            4,
        ),
    }
    for field in RATING_FIELDS:
        values = [row[field] for row in reviews]
        result[f"average_{field}"] = round(statistics.fmean(values), 4)
        result[f"stdev_{field}"] = round(statistics.stdev(values), 4) if len(values) > 1 else 0.0
    return result


def _group_key(sample: dict, include_scenario: bool = False) -> tuple[str, ...]:
    base = (sample["language"], sample["engine"], sample["voice_id"])
    return base + ((sample["scenario_id"],) if include_scenario else ())


def _build_rankings(samples: list[dict], include_scenario: bool = False) -> dict[str, list[dict]]:
    groups: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    for sample in samples:
        if sample.get("human_review_summary", {}).get("review_count", 0) > 0:
            groups[_group_key(sample, include_scenario)].append(sample)

    output: dict[str, list[dict]] = defaultdict(list)
    for key, group_samples in groups.items():
        language, engine, voice_id = key[:3]
        reviews = [
            review
            for sample in group_samples
            for review in sample.get("human_reviews", [])
        ]
        summary = _average_reviews(reviews)
        first = group_samples[0]
        rights = first.get("rights") if isinstance(first.get("rights"), dict) else {}
        row = {
            "language": language,
            "engine": engine,
            "engine_label": first.get("engine_label", engine),
            "voice_id": voice_id,
            "voice_label": first.get("voice_label", voice_id),
            "sample_count": len(group_samples),
            **summary,
            "rights_status": rights.get("status", "unknown"),
            "commercial_use": rights.get("commercial_use", "not-established"),
        }
        if include_scenario:
            row["scenario"] = key[3]
            row["scenario_title"] = first.get("scenario_title", key[3])
        output[language].append(row)

    for language, rows in output.items():
        rows.sort(key=lambda row: (
            -row["average_overall"],
            -row["average_naturalness"],
            -row["average_pronunciation"],
            row["engine_label"].casefold(),
            row["voice_label"].casefold(),
        ))
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
    return dict(output)


def merge(analysis_path: Path, scores_path: Path, output_path: Path, summary_csv: Path | None = None) -> dict:
    manifest = _load_manifest(analysis_path)
    sample_index = _index_samples(manifest)
    submitted = read_scores(scores_path, sample_index)

    samples = []
    for original in manifest["samples"]:
        sample = dict(original)
        reviews = submitted.get(sample["blind_sample_id"], [])
        sample["human_reviews"] = reviews
        sample["human_review_summary"] = (
            _average_reviews(reviews)
            if reviews else {"review_count": 0, "status": "pending"}
        )
        samples.append(sample)

    completed = sum(1 for sample in samples if sample["human_review_summary"]["review_count"] > 0)
    review_count = sum(sample["human_review_summary"]["review_count"] for sample in samples)
    result = dict(manifest)
    result["samples"] = samples
    result["human_review_status"] = "scored" if completed == len(samples) else "partially_scored"
    result["human_review_summary"] = {
        "completed_sample_count": completed,
        "total_sample_count": len(samples),
        "review_count": review_count,
        "rating_scale": "1 (poor) to 5 (excellent)",
        "overall_formula": "mean of naturalness, pronunciation, prosody and emotion",
        "interpretation": (
            "Blind human preference ratings for this review cohort only. They are not standardized MOS, "
            "a universal quality guarantee, or proof of commercial rights. Rights status remains an "
            "independent production gate and must not be inferred from a high listener score."
        ),
    }
    result["voice_rankings_by_language"] = _build_rankings(samples, include_scenario=False)
    result["voice_rankings_by_language_and_scenario"] = _build_rankings(samples, include_scenario=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if summary_csv:
        summary_csv.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            row
            for language in sorted(result["voice_rankings_by_language"])
            for row in result["voice_rankings_by_language"][language]
        ]
        with summary_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows({field: row.get(field, "") for field in CSV_OUTPUT_FIELDS} for row in rows)
    return result


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", required=True, type=Path, help="Private benchmark.json analyst manifest")
    parser.add_argument("--scores", required=True, type=Path, help="CSV exported from the blind listening gallery")
    parser.add_argument("--output", required=True, type=Path, help="Destination scored benchmark JSON")
    parser.add_argument("--summary-csv", type=Path, help="Optional ranked summary CSV")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = merge(args.analysis, args.scores, args.output, args.summary_csv)
    except Exception as exc:
        print(f"[tts-blind-score-merge] ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    summary = result["human_review_summary"]
    print(
        f"[tts-blind-score-merge] COMPLETE {summary['completed_sample_count']}/"
        f"{summary['total_sample_count']} samples; {summary['review_count']} reviews; "
        f"ranked {sum(len(rows) for rows in result['voice_rankings_by_language'].values())} language-specific candidates",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
