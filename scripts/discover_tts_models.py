#!/usr/bin/env python3
"""Create a dated, rights-aware discovery snapshot of trending Hugging Face TTS models.

This is a free metadata-only scan of the public Hub API. It never downloads model
weights, generates audio, calls a paid provider, or promotes a candidate to production.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

API_URL = "https://huggingface.co/api/models"
MAX_LIMIT = 100
QUERY_PLAN = (
    ("all_trending", "trendingScore", None),
    ("all_downloads", "downloads", None),
    ("all_likes", "likes", None),
    ("vi_search_trending", "trendingScore", "Vietnamese"),
    ("vi_search_downloads", "downloads", "Vietnamese"),
    ("en_search_trending", "trendingScore", "English"),
    ("en_search_downloads", "downloads", "English"),
)


def _request_models(
    sort: str,
    limit: int,
    search: str | None,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout: int = 30,
) -> list[dict[str, Any]]:
    if sort not in {"trendingScore", "downloads", "likes"}:
        raise ValueError(f"Unsupported Hub sort: {sort}")
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    params = [
        ("pipeline_tag", "text-to-speech"),
        ("sort", sort),
        ("limit", str(limit)),
    ]
    # The Hub OpenAPI array parameter is sent as repeated expand keys, not one
    # comma-joined value. This is the same encoding used by its API clients.
    params.extend(
        ("expand", field)
        for field in (
            "downloads", "likes", "tags", "trendingScore", "createdAt",
            "lastModified", "pipeline_tag", "library_name", "gated",
        )
    )
    if search:
        if search not in {"Vietnamese", "English"}:
            raise ValueError(f"Unsupported language discovery search: {search}")
        params.append(("search", search))
    url = API_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Nolane-VoiceStudio-TTS-Discovery/1.0",
        },
        method="GET",
    )
    for attempt in range(2):
        try:
            with opener(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, list):
                raise ValueError("Hugging Face Hub model listing did not return a JSON array")
            return [row for row in payload if isinstance(row, dict)]
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:1000]
            if attempt == 0 and (exc.code == 429 or 500 <= exc.code <= 599):
                time.sleep(2)
                continue
            raise RuntimeError(
                f"Hugging Face Hub API returned HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            if attempt == 0:
                time.sleep(1)
                continue
            raise RuntimeError(f"Hugging Face Hub API request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("Hugging Face Hub API returned invalid JSON") from exc
    raise RuntimeError("Hugging Face Hub API request failed after bounded retry")


def _language_tags(tags: list[Any]) -> list[str]:
    return sorted({
        str(item).split(":", 1)[1].lower()
        for item in tags
        if str(item).startswith("language:")
    })


def _license(tags: list[Any], row: dict[str, Any]) -> str | None:
    card = row.get("cardData") or row.get("card_data") or {}
    if isinstance(card, dict) and card.get("license"):
        return str(card["license"])
    for item in tags:
        tag = str(item)
        if tag.startswith("license:"):
            return tag.split(":", 1)[1]
    return None


def _normalize(row: dict[str, Any]) -> dict[str, Any]:
    tags = row.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    return {
        "model_id": str(row.get("id") or row.get("modelId") or "").strip(),
        "pipeline_tag": row.get("pipeline_tag") or row.get("pipelineTag") or "text-to-speech",
        "library_name": row.get("library_name") or row.get("libraryName"),
        "downloads": row.get("downloads"),
        "likes": row.get("likes"),
        "trending_score": row.get("trendingScore", row.get("trending_score")),
        "created_at": row.get("createdAt") or row.get("created_at"),
        "last_modified": row.get("lastModified") or row.get("last_modified"),
        "gated": row.get("gated"),
        "language_tags": _language_tags(tags),
        "license": _license(tags, row),
        "tags": sorted({str(tag) for tag in tags})[:100],
        "discovery_status": "discovery_only_not_benchmarked_or_rights_cleared",
        "rights_review": "required_before_model_download_or_production_use",
        "human_listening_review": "required_before_voice_quality_claim",
    "language_search_hints": [],
    }


def collect_discovery(
    limit: int = 40,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")

    merged: dict[str, dict[str, Any]] = {}
    source_results = []
    source_errors = []
    for source_name, sort, search_term in QUERY_PLAN:
        try:
            rows = _request_models(sort, limit, search_term, opener=opener)
            source_results.append({
                "source": source_name,
                "sort": sort,
                "search_term": search_term,
                "count": len(rows),
            })
            for rank, raw in enumerate(rows, start=1):
                record = _normalize(raw)
                model_id = record["model_id"]
                if not model_id:
                    continue
                target = merged.setdefault(
                    model_id,
                    {**record, "signal_ranks": {}, "discovered_by": []},
                )
                target["signal_ranks"][source_name] = rank
                target["discovered_by"].append(source_name)
                if search_term and search_term not in target["language_search_hints"]:
                    target["language_search_hints"].append(search_term)
                for key, value in record.items():
                    if value is not None and value != []:
                        target[key] = value
        except Exception as exc:
            source_errors.append({
                "source": source_name,
                "error": f"{type(exc).__name__}: {exc}",
            })

    if not source_results:
        errors = "; ".join(row["error"] for row in source_errors)
        raise RuntimeError("All Hugging Face discovery queries failed: " + errors)

    models = sorted(
        merged.values(),
        key=lambda item: (
            0 if "vi_trending" in item["signal_ranks"] else 1,
            item["signal_ranks"].get("vi_trending", 10_000),
            item["signal_ranks"].get("all_trending", 10_000),
            -(int(item.get("downloads") or 0)),
            item["model_id"],
        ),
    )
    timestamp = (
        now or datetime.now(timezone.utc)
    ).astimezone(timezone.utc).replace(microsecond=0).isoformat()
    return {
        "schema_version": 1,
        "catalog_type": "tts_model_discovery_snapshot",
        "generated_at": timestamp,
        "limit_per_query": limit,
        "source": "Hugging Face Hub public model API",
        "source_url": API_URL,
        "query_plan": [
            {"source": name, "sort": sort, "search_term": search_term}
            for name, sort, search_term in QUERY_PLAN
        ],
        "source_results": source_results,
        "source_errors": source_errors,
        "model_count": len(models),
        "models": models,
        "limitations": [
            "Hub downloads, likes and trending scores are discovery/adoption signals, not human preference or proof of use by creators/channels.",
            "A model repository license tag does not clear weights, datasets, tokenizers, speaker recordings, generated identities or redistribution rights.",
            "Language tags may be absent or incomplete; search-term matches are unverified hints only. Verify each model card and run native-language smoke tests.",
            "This report does not download model weights, create audio, save provider voices or promote any candidate to production.",
        ],
    }


def _md(value: Any) -> str:
    return str(value if value is not None else "—").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def write_report(payload: dict[str, Any], output: Path) -> tuple[Path, Path]:
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "discovery-report.json"
    readme_path = output / "README.md"
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# TTS model discovery snapshot",
        "",
        f"- Generated: {payload['generated_at']}",
        f"- Models discovered: {payload['model_count']}",
        f"- Limit per query: {payload['limit_per_query']}",
        f"- Successful sources: {len(payload['source_results'])}/{len(payload['query_plan'])}",
        f"- Source errors: {len(payload['source_errors'])}",
        "",
        "This is a discovery report, not a quality ranking or approved production catalog.",
        "Review model cards, exact weights/dataset licenses, supported Vietnamese/English",
        "coverage, CPU/GPU requirements and blind-listening results before selecting a model.",
        "",
        "| Model | Downloads | Likes | Trending score | Languages | License tag |",
        "|---|---:|---:|---:|---|---|",
    ]
    for row in payload["models"]:
        languages = ", ".join(row.get("language_tags") or []) or "not tagged"
        hints = ", ".join(row.get("language_search_hints") or [])
        if hints:
            languages += f"; unverified search hint: {hints}"
        lines.append(
            f"| [{_md(row['model_id'])}](https://huggingface.co/{_md(row['model_id'])}) "
            f"| {_md(row.get('downloads'))} "
            f"| {_md(row.get('likes'))} "
            f"| {_md(row.get('trending_score'))} "
            f"| {_md(languages)} | {_md(row.get('license') or 'not declared')} |"
        )
    readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path, readme_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--output", type=Path, default=Path("dist/tts-discovery"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.limit <= MAX_LIMIT:
        raise ValueError(f"--limit must be between 1 and {MAX_LIMIT}")
    payload = collect_discovery(args.limit)
    report, readme = write_report(payload, args.output)
    print(
        f"Discovered {payload['model_count']} TTS models; "
        f"{len(payload['source_errors'])} source query errors."
    )
    print(f"Report: {report}")
    print(f"Summary: {readme}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[tts-discovery] ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
