#!/usr/bin/env python3
"""Promote human-approved ElevenLabs Voice Design previews to private account voices.

This does not generate new audio. It calls POST /v1/text-to-voice using an
existing generated_voice_id from a private Voice Design analysis artifact.
Voice Design voices remain workspace-scoped and cannot be published to the
public ElevenLabs Voice Library.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

CREATE_URL = "https://api.elevenlabs.io/v1/text-to-voice"
MAX_PROMOTION_BATCH = 8
SCORE_FIELDS = (
    "naturalness",
    "pronunciation",
    "accent_fit",
    "prosody",
    "distinctiveness",
    "overall",
)


def load_analysis(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read the private preview analysis file: {exc}") from exc
    if data.get("provider") != "ElevenLabs Voice Design":
        raise ValueError("The analysis file is not an ElevenLabs Voice Design artifact")
    records = data.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("Analysis artifact has no preview records")
    seen: set[str] = set()
    for row in records:
        blind_id = str(row.get("blind_sample_id", "")).strip()
        if not blind_id or blind_id in seen:
            raise ValueError("Analysis artifact has a missing or duplicate blind_sample_id")
        seen.add(blind_id)
        if not row.get("generated_voice_id"):
            raise ValueError(f"Analysis record {blind_id} has no generated_voice_id")
        if not 20 <= len(str(row.get("voice_description", ""))) <= 1000:
            raise ValueError(f"Analysis record {blind_id} has an invalid voice description length")
        if row.get("shareability") != "not_shareable_to_public_elevenlabs_voice_library":
            raise ValueError(f"Analysis record {blind_id} has an unexpected sharing classification")
    return data


def _score(value: str, field: str, blind_id: str) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{blind_id}: {field} must be a score from 1 to 5") from exc
    if not 1.0 <= score <= 5.0:
        raise ValueError(f"{blind_id}: {field} must be between 1 and 5")
    return score


def load_ratings(path: Path) -> dict[str, dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"blind_sample_id", "language", "approve", *SCORE_FIELDS}
            fields = set(reader.fieldnames or [])
            missing = required - fields
            if missing:
                raise ValueError("Human review CSV is missing columns: " + ", ".join(sorted(missing)))
            ratings: dict[str, dict[str, Any]] = {}
            for row in reader:
                blind_id = str(row.get("blind_sample_id", "")).strip()
                if not blind_id:
                    continue
                if blind_id in ratings:
                    raise ValueError(f"Human review CSV has duplicate blind_sample_id {blind_id}")
                approved = str(row.get("approve", "")).strip().lower() in {"yes", "true", "1", "approved"}
                item: dict[str, Any] = {
                    "blind_sample_id": blind_id,
                    "language": str(row.get("language", "")).strip().upper(),
                    "approved": approved,
                    "notes": str(row.get("notes", "")).strip(),
                }
                if approved:
                    item["scores"] = {
                        field: _score(row.get(field, ""), field, blind_id)
                        for field in SCORE_FIELDS
                    }
                ratings[blind_id] = item
    except OSError as exc:
        raise ValueError(f"Cannot read human review CSV: {exc}") from exc
    return ratings


def select_candidates(
    analysis: dict[str, Any],
    ratings: dict[str, dict[str, Any]],
    *,
    max_voices: int = 4,
    minimum_overall: float = 4.0,
    minimum_naturalness: float = 4.0,
    minimum_pronunciation: float = 4.0,
    minimum_accent_fit: float = 4.0,
    minimum_prosody: float = 3.0,
    minimum_distinctiveness: float = 3.0,
) -> list[dict[str, Any]]:
    if not 1 <= max_voices <= MAX_PROMOTION_BATCH:
        raise ValueError(f"max_voices must be between 1 and {MAX_PROMOTION_BATCH}")

    records = {str(row["blind_sample_id"]): row for row in analysis["records"]}
    unknown = sorted(set(ratings) - set(records))
    if unknown:
        raise ValueError("Human review contains IDs absent from the analysis artifact: " + ", ".join(unknown))

    thresholds = {
        "overall": minimum_overall,
        "naturalness": minimum_naturalness,
        "pronunciation": minimum_pronunciation,
        "accent_fit": minimum_accent_fit,
        "prosody": minimum_prosody,
        "distinctiveness": minimum_distinctiveness,
    }
    selected = []
    for blind_id, rating in ratings.items():
        if not rating["approved"]:
            continue
        scores = rating["scores"]
        if any(scores[field] < threshold for field, threshold in thresholds.items()):
            continue
        record = records[blind_id]
        if record.get("generation_state") not in (None, "preview_generated_not_saved_as_persistent_voice"):
            raise ValueError(f"{blind_id}: preview is not in a promotable state")
        selected.append({
            **record,
            "human_review": {
                "approved": True,
                "scores": scores,
                "notes": rating["notes"],
            },
        })

    selected.sort(
        key=lambda row: (
            row["human_review"]["scores"]["overall"],
            row["human_review"]["scores"]["pronunciation"],
            row["human_review"]["scores"]["naturalness"],
            row["human_review"]["scores"]["accent_fit"],
            row["human_review"]["scores"]["prosody"],
            row["human_review"]["scores"]["distinctiveness"],
            row["blind_sample_id"],
        ),
        reverse=True,
    )
    return selected[:max_voices]


def build_voice_payload(record: dict[str, Any]) -> dict[str, Any]:
    blind_id = str(record.get("blind_sample_id", "")).strip()
    generated_voice_id = str(record.get("generated_voice_id", "")).strip()
    language = str(record.get("language", "")).strip().lower()
    accent_id = re.sub(r"[^a-z0-9-]+", "-", str(record.get("accent_id", "neutral")).lower()).strip("-")
    description = str(record.get("voice_description", "")).strip()
    if not blind_id or not generated_voice_id:
        raise ValueError("Promotable records must contain blind_sample_id and generated_voice_id")
    if language not in {"vi", "en"}:
        raise ValueError(f"{blind_id}: only Vietnamese and English voices are supported")
    if not 20 <= len(description) <= 1000:
        raise ValueError(f"{blind_id}: voice_description must contain 20-1000 characters")
    if record.get("shareability") != "not_shareable_to_public_elevenlabs_voice_library":
        raise ValueError(f"{blind_id}: refusing to promote a record with unexpected sharing rights")

    name = f"VS-{language.upper()}-{accent_id[:12]}-{blind_id[-3:]}"
    if len(name) > 40:
        name = name[:40]
    dimensions = record.get("dimensions") or {}
    labels = {
        "language": language,
        "locale": str(record.get("locale", "")),
        "accent": accent_id,
        "use_case": str(record.get("intended_use_case") or dimensions.get("use_case", "")),
        "archetype": str(record.get("market_archetype_id") or ""),
        "review": "human-approved",
    }
    labels = {key: value for key, value in labels.items() if value}
    return {
        "voice_name": name,
        "voice_description": description,
        "generated_voice_id": generated_voice_id,
        "labels": labels,
    }


def create_voice(
    record: dict[str, Any],
    api_key: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout: int = 60,
) -> dict[str, Any]:
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY is required")
    payload = build_voice_payload(record)
    request = urllib.request.Request(
        CREATE_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "xi-api-key": api_key},
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"ElevenLabs create-voice HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"ElevenLabs create-voice network failure: {exc.reason}") from exc
    voice_id = str(result.get("voice_id", "")).strip()
    if not voice_id:
        raise RuntimeError("ElevenLabs create-voice response did not contain voice_id")
    return {
        "blind_sample_id": record["blind_sample_id"],
        "voice_id": voice_id,
        "voice_name": payload["voice_name"],
        "language": record["language"],
        "locale": record.get("locale"),
        "accent_id": record.get("accent_id"),
        "market_archetype_id": record.get("market_archetype_id"),
        "human_review": record["human_review"],
        "shareability": "workspace_only_not_public_voice_library",
        "status": "created",
    }


def write_ledger(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def run(args: argparse.Namespace) -> int:
    if not args.confirm_voice_creation:
        raise ValueError("Persistent voice creation is blocked. Set --confirm-voice-creation explicitly.")
    if not 1 <= args.max_voices <= MAX_PROMOTION_BATCH:
        raise ValueError(f"max_voices must be between 1 and {MAX_PROMOTION_BATCH}")
    if not 1.0 <= args.minimum_overall <= 5.0 or not 1.0 <= args.minimum_pronunciation <= 5.0:
        raise ValueError("minimum scores must be between 1 and 5")
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise ValueError("Set ELEVENLABS_API_KEY in GitHub Actions secrets")

    analysis = load_analysis(Path(args.analysis))
    ratings = load_ratings(Path(args.ratings))
    selected = select_candidates(
        analysis,
        ratings,
        max_voices=args.max_voices,
        minimum_overall=args.minimum_overall,
        minimum_naturalness=args.minimum_naturalness,
        minimum_pronunciation=args.minimum_pronunciation,
        minimum_accent_fit=args.minimum_accent_fit,
        minimum_prosody=args.minimum_prosody,
        minimum_distinctiveness=args.minimum_distinctiveness,
    )
    if not selected:
        raise ValueError("No candidates passed explicit human approval and all score thresholds")

    ledger: dict[str, Any] = {
        "schema_version": 1,
        "provider": "ElevenLabs",
        "operation": "create_voice_from_existing_voice_design_preview",
        "created_from_previews": True,
        "new_preview_generations": 0,
        "public_voice_library_publications": 0,
        "workspace_only": True,
        "selected_count": len(selected),
        "created_count": 0,
        "failed_count": 0,
        "records": [],
    }
    output_path = Path(args.output)
    write_ledger(output_path, ledger)

    failures = []
    for record in selected:
        try:
            created = create_voice(record, api_key)
            ledger["records"].append(created)
            ledger["created_count"] += 1
            write_ledger(output_path, ledger)
        except Exception as exc:
            failure = {
                "blind_sample_id": record["blind_sample_id"],
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
            failures.append(failure)
            ledger["records"].append(failure)
            ledger["failed_count"] += 1
            write_ledger(output_path, ledger)

    ledger["completed"] = not failures
    write_ledger(output_path, ledger)
    print(
        f"Promoted {ledger['created_count']} human-approved voices; "
        f"failed={ledger['failed_count']}; new preview generations=0; public publications=0."
    )
    return 1 if failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", required=True)
    parser.add_argument("--ratings", required=True)
    parser.add_argument("--output", default="dist/voice-promotion-ledger.json")
    parser.add_argument("--max-voices", type=int, default=4)
    parser.add_argument("--minimum-overall", type=float, default=4.0)
    parser.add_argument("--minimum-naturalness", type=float, default=4.0)
    parser.add_argument("--minimum-pronunciation", type=float, default=4.0)
    parser.add_argument("--minimum-accent-fit", type=float, default=4.0)
    parser.add_argument("--minimum-prosody", type=float, default=3.0)
    parser.add_argument("--minimum-distinctiveness", type=float, default=3.0)
    parser.add_argument("--confirm-voice-creation", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.max_voices <= MAX_PROMOTION_BATCH:
        parser.error(f"--max-voices must be between 1 and {MAX_PROMOTION_BATCH}")
    return args


def main() -> int:
    try:
        return run(parse_args())
    except Exception as exc:
        print(f"[voice-promotion] ERROR: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
