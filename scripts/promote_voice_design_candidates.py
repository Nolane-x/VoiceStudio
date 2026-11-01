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
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode
from pathlib import Path
from typing import Any, Callable

CREATE_URL = "https://api.elevenlabs.io/v1/text-to-voice"
LIST_VOICES_URL = "https://api.elevenlabs.io/v2/voices"
PROMOTION_MARKER_LABEL = "voicestudio_generated_voice_id"
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
    review = record.get("human_review")
    if not isinstance(review, dict) or review.get("approved") is not True:
        raise ValueError(f"{blind_id}: persistent voice creation requires explicit human approval")
    scores = review.get("scores")
    if not isinstance(scores, dict) or not set(SCORE_FIELDS).issubset(scores):
        raise ValueError(f"{blind_id}: human review must contain all required scores")
    try:
        numeric_scores = {field: float(scores[field]) for field in SCORE_FIELDS}
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{blind_id}: human review scores must be numeric") from exc
    if any(not 1.0 <= value <= 5.0 for value in numeric_scores.values()):
        raise ValueError(f"{blind_id}: human review scores must be between 1 and 5")
    thresholds = {
        "overall": 4.0, "naturalness": 4.0, "pronunciation": 4.0,
        "accent_fit": 4.0, "prosody": 3.0, "distinctiveness": 3.0,
    }
    if any(numeric_scores[field] < minimum for field, minimum in thresholds.items()):
        raise ValueError(f"{blind_id}: human review scores do not meet promotion thresholds")
    if record.get("shareability") != "not_shareable_to_public_elevenlabs_voice_library":
        raise ValueError(f"{blind_id}: refusing to promote a record with unexpected sharing rights")

    name = f"VS-{language.upper()}-{accent_id[:12]}-{blind_id[-3:]}"
    if len(name) > 40:
        name = name[:40]
    dimensions = record.get("dimensions") or {}
    labels = {
        "language": language,
        PROMOTION_MARKER_LABEL: generated_voice_id,
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


class VoiceCreationOutcomeUnknown(RuntimeError):
    """A create request may have succeeded, but the client did not receive a definitive result."""


def find_existing_voice(
    record: dict[str, Any],
    api_key: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout: int = 30,
    max_pages: int = 20,
) -> dict[str, Any] | None:
    """Reconcile a preview by searching the account for its exact unique marker label."""
    generated_id = str(record.get("generated_voice_id", "")).strip()
    if not generated_id or not api_key:
        raise ValueError("generated_voice_id and ELEVENLABS_API_KEY are required for reconciliation")

    page_token: str | None = None
    seen_tokens: set[str] = set()
    for _ in range(max_pages):
        query = {
            "search": generated_id,
            "page_size": "100",
            "include_total_count": "false",
            "voice_type": "non-community",
        }
        if page_token:
            query["next_page_token"] = page_token
        request = urllib.request.Request(
            f"{LIST_VOICES_URL}?{urlencode(query)}",
            headers={"xi-api-key": api_key},
            method="GET",
        )
        try:
            with opener(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"ElevenLabs voice reconciliation failed: {exc}") from exc

        voices = payload.get("voices")
        if not isinstance(voices, list):
            raise RuntimeError("ElevenLabs List Voices response has no voices array")
        matches = [
            voice for voice in voices
            if (voice.get("labels") or {}).get(PROMOTION_MARKER_LABEL) == generated_id
            and voice.get("voice_id")
        ]
        if len(matches) > 1:
            raise RuntimeError(
                f"Multiple account voices match promotion marker {generated_id}; "
                "manual account reconciliation is required"
            )
        if matches:
            return matches[0]

        if not payload.get("has_more"):
            return None
        token = payload.get("next_page_token")
        if not isinstance(token, str) or not token or token in seen_tokens:
            raise RuntimeError("ElevenLabs List Voices returned an invalid pagination token")
        seen_tokens.add(token)
        page_token = token

    raise RuntimeError("ElevenLabs List Voices exceeded the 20-page reconciliation safety limit")


def _ledger_record_from_voice(
    record: dict[str, Any],
    voice: dict[str, Any],
    *,
    reconciled: bool,
) -> dict[str, Any]:
    payload = build_voice_payload(record)
    return {
        "blind_sample_id": record["blind_sample_id"],
        "generated_voice_id": record["generated_voice_id"],
        "voice_id": voice["voice_id"],
        "voice_name": voice.get("name") or payload["voice_name"],
        "language": record["language"],
        "locale": record.get("locale"),
        "accent_id": record.get("accent_id"),
        "market_archetype_id": record.get("market_archetype_id"),
        "human_review": record["human_review"],
        "reconciled_existing": reconciled,
        "shareability": "workspace_only_not_public_voice_library",
        "status": "created",
    }


def _reconcile_after_ambiguous_post(
    record: dict[str, Any],
    api_key: str,
    *,
    opener: Callable[..., Any],
    sleep: Callable[[float], None],
) -> dict[str, Any] | None:
    last_error: Exception | None = None
    for attempt, delay in enumerate((0, 1, 2), start=1):
        if delay:
            sleep(delay)
        try:
            existing = find_existing_voice(record, api_key, opener=opener)
            if existing:
                return existing
            last_error = None
        except Exception as exc:
            last_error = exc
    if last_error:
        raise VoiceCreationOutcomeUnknown(
            f"Create POST may have succeeded but List Voices reconciliation failed: {last_error}"
        ) from last_error
    return None


def create_voice(
    record: dict[str, Any],
    api_key: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout: int = 60,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY is required")

    # A retry first checks whether an earlier POST already created this exact preview.
    existing = find_existing_voice(record, api_key, opener=opener)
    if existing:
        return _ledger_record_from_voice(record, existing, reconciled=True)

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
        voice_id = str(result.get("voice_id", "")).strip()
        if not voice_id:
            raise VoiceCreationOutcomeUnknown(
                "Create Voice returned success without voice_id; reconcile through List Voices before retrying"
            )
        return _ledger_record_from_voice(
            record,
            {"voice_id": voice_id, "name": result.get("name") or payload["voice_name"]},
            reconciled=False,
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        if exc.code == 409 or exc.code >= 500:
            existing = _reconcile_after_ambiguous_post(
                record, api_key, opener=opener, sleep=sleep
            )
            if existing:
                return _ledger_record_from_voice(record, existing, reconciled=True)
            raise VoiceCreationOutcomeUnknown(
                f"Create Voice returned HTTP {exc.code}; no matching account voice is visible. "
                "Check My Voices before retrying. " + detail
            ) from exc
        raise RuntimeError(f"ElevenLabs create-voice HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        existing = _reconcile_after_ambiguous_post(
            record, api_key, opener=opener, sleep=sleep
        )
        if existing:
            return _ledger_record_from_voice(record, existing, reconciled=True)
        raise VoiceCreationOutcomeUnknown(
            "The POST may have succeeded, but List Voices did not confirm the result. "
            "Check My Voices before another POST."
        ) from exc


def write_ledger(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_previous_ledger(path: Path | None, source_run_id: str) -> dict[str, Any]:
    if path is None:
        return {"records": []}
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read previous promotion ledger: {exc}") from exc
    if previous.get("provider") != "ElevenLabs":
        raise ValueError("Previous ledger is not an ElevenLabs promotion ledger")
    if previous.get("operation") != "create_voice_from_existing_voice_design_preview":
        raise ValueError("Previous ledger has an unexpected operation")
    if str(previous.get("source_run_id", "")) != str(source_run_id):
        raise ValueError("Previous ledger belongs to a different Voice Design source run")
    records = previous.get("records")
    if not isinstance(records, list):
        raise ValueError("Previous ledger has no records list")
    seen: set[str] = set()
    for row in records:
        blind_id = str(row.get("blind_sample_id", "")).strip()
        if not blind_id or blind_id in seen:
            raise ValueError("Previous ledger contains a missing or duplicate blind_sample_id")
        seen.add(blind_id)
        if row.get("status") not in {"created", "failed", "unknown"}:
            raise ValueError(f"Previous ledger record {blind_id} has an unknown status")
        if row.get("status") == "created" and not row.get("voice_id"):
            raise ValueError(f"Previous ledger record {blind_id} has no saved voice_id")
        if row.get("status") == "unknown" and not row.get("generated_voice_id"):
            raise ValueError(f"Unknown ledger record {blind_id} has no generated_voice_id to reconcile")
    return previous


def exclude_previously_created(
    candidates: list[dict[str, Any]],
    previous_ledger: dict[str, Any],
) -> list[dict[str, Any]]:
    created_ids = {
        str(row["blind_sample_id"])
        for row in previous_ledger.get("records", [])
        if row.get("status") == "created"
    }
    return [
        row for row in candidates
        if str(row["blind_sample_id"]) not in created_ids
    ]


def _refresh_ledger_counts(ledger: dict[str, Any]) -> None:
    records = ledger["records"]
    ledger["created_count"] = sum(row.get("status") == "created" for row in records)
    ledger["failed_count"] = sum(row.get("status") == "failed" for row in records)
    ledger["unknown_count"] = sum(row.get("status") == "unknown" for row in records)
    ledger["completed"] = ledger["failed_count"] == 0 and ledger["unknown_count"] == 0


def run(args: argparse.Namespace) -> int:
    if not args.confirm_voice_creation:
        raise ValueError("Persistent voice creation is blocked. Set --confirm-voice-creation explicitly.")
    if not 1 <= args.max_voices <= MAX_PROMOTION_BATCH:
        raise ValueError(f"max_voices must be between 1 and {MAX_PROMOTION_BATCH}")
    if not 1.0 <= args.minimum_overall <= 5.0 or not 1.0 <= args.minimum_pronunciation <= 5.0:
        raise ValueError("minimum scores must be between 1 and 5")
    source_run_id = str(args.source_run_id).strip()
    if not source_run_id.isdigit() or int(source_run_id) <= 0:
        raise ValueError("source_run_id must be a positive GitHub Actions run ID")
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
    previous = load_previous_ledger(
        Path(args.previous_ledger) if args.previous_ledger else None,
        source_run_id,
    )
    selected_new = exclude_previously_created(selected, previous)

    records_by_id = {
        str(row["blind_sample_id"]): row
        for row in previous.get("records", [])
    }
    ledger: dict[str, Any] = {
        "schema_version": 1,
        "provider": "ElevenLabs",
        "operation": "create_voice_from_existing_voice_design_preview",
        "source_run_id": source_run_id,
        "previous_ledger_used": bool(args.previous_ledger),
        "created_from_previews": True,
        "new_preview_generations": 0,
        "public_voice_library_publications": 0,
        "workspace_only": True,
        "selected_count": len(selected),
        "new_selected_count": len(selected_new),
        "created_count": 0,
        "failed_count": 0,
        "records": list(records_by_id.values()),
    }
    _refresh_ledger_counts(ledger)
    output_path = Path(args.output)
    write_ledger(output_path, ledger)

    if not selected_new:
        print(
            f"No new voice requests: selected={len(selected)}, "
            f"already created={ledger['created_count']}, failed in ledger={ledger['failed_count']}. "
            "No provider calls were made."
        )
        return 1 if ledger["failed_count"] or ledger.get("unknown_count", 0) else 0

    previous_unknown = {
        str(row["blind_sample_id"]): row
        for row in previous.get("records", [])
        if row.get("status") == "unknown"
    }
    resolved_unknown: set[str] = set()
    for record in selected_new:
        blind_id = str(record["blind_sample_id"])
        if blind_id not in previous_unknown:
            continue
        existing = find_existing_voice(record, api_key)
        if existing:
            records_by_id[blind_id] = _ledger_record_from_voice(record, existing, reconciled=True)
            resolved_unknown.add(blind_id)
            ledger["records"] = sorted(records_by_id.values(), key=lambda row: str(row["blind_sample_id"]))
            _refresh_ledger_counts(ledger)
            write_ledger(output_path, ledger)
            continue
        if not args.confirm_retry_unknown:
            raise ValueError(
                f"{blind_id} has an ambiguous previous POST and no matching account voice is visible. "
                "Check My Voices, then rerun with --confirm-retry-unknown only after confirming it was not created."
            )
    selected_new = [row for row in selected_new if str(row["blind_sample_id"]) not in resolved_unknown]

    failures_this_run = 0
    for record in selected_new:
        blind_id = str(record["blind_sample_id"])
        try:
            created = create_voice(record, api_key)
            records_by_id[blind_id] = created
        except VoiceCreationOutcomeUnknown as exc:
            unknown = {
                "blind_sample_id": blind_id,
                "generated_voice_id": record["generated_voice_id"],
                "status": "unknown",
                "error": f"{type(exc).__name__}: {exc}",
            }
            records_by_id[blind_id] = unknown
            failures_this_run += 1
        except Exception as exc:
            failure = {
                "blind_sample_id": blind_id,
                "generated_voice_id": record["generated_voice_id"],
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
            records_by_id[blind_id] = failure
            failures_this_run += 1

        ledger["records"] = sorted(
            records_by_id.values(),
            key=lambda row: str(row["blind_sample_id"]),
        )
        _refresh_ledger_counts(ledger)
        write_ledger(output_path, ledger)

    print(
        f"Created {ledger['created_count']} unique workspace voices "
        f"(newly selected={len(selected_new)}, failures this run={failures_this_run}, "
        f"cumulative failed={ledger['failed_count']}, unknown={ledger.get('unknown_count', 0)}); "
        "new preview generations=0; public publications=0."
    )
    return 1 if ledger["failed_count"] or ledger.get("unknown_count", 0) else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", required=True)
    parser.add_argument("--ratings", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--previous-ledger", default=None)
    parser.add_argument("--confirm-retry-unknown", action="store_true")
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
