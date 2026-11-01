#!/usr/bin/env python3
"""Discover popular, high-quality public ElevenLabs shared voices.

Metadata-only discovery. It does not generate audio, copy voice assets, clone
speakers, or grant rights beyond the provider's voice-sharing terms.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

API_URL = "https://api.elevenlabs.io/v1/shared-voices"
DOCS_URL = "https://elevenlabs.io/docs/api-reference/voices/voice-library/get-shared"
ALLOWED_CATEGORIES = ("high_quality", "professional")
SORTS = ("trending", "usage_character_count_1y", "cloned_by_count")
LANGUAGES = ("vi", "en")
PAGE_SIZE = 100
MAX_PAGES = 5
USER_AGENT = "VoiceStudio-VoiceDiscovery/1.0"


def _request_json(url: str, api_key: str | None, timeout: int = 30) -> dict:
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if api_key:
        headers["xi-api-key"] = api_key
    request = urllib.request.Request(url, headers=headers, method="GET")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
                if len(payload) > 12 * 1024 * 1024:
                    raise RuntimeError("ElevenLabs voice page exceeded the 12 MiB safety limit")
                value = json.loads(payload.decode("utf-8"))
                if not isinstance(value, dict):
                    raise RuntimeError("ElevenLabs shared-voices response must be a JSON object")
                return value
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if retryable and attempt < 3:
                retry_after = exc.headers.get("Retry-After", "")
                try:
                    delay = min(20.0, max(1.0, float(retry_after)))
                except (TypeError, ValueError):
                    delay = float(2 ** attempt)
                time.sleep(delay)
                continue
            detail = exc.read(1200).decode("utf-8", errors="replace")
            raise RuntimeError(f"ElevenLabs shared-voices API returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < 3:
                time.sleep(float(2 ** attempt))
                continue
            raise RuntimeError(f"ElevenLabs shared-voices API request failed: {exc}") from exc
    raise RuntimeError("ElevenLabs shared-voices API retries were exhausted")


def fetch_shared_voices(
    *,
    language: str,
    category: str,
    sort: str,
    page: int,
    api_key: str | None = None,
) -> dict:
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    if category not in ALLOWED_CATEGORIES:
        raise ValueError(f"Unsupported shared-voice category: {category}")
    if sort not in SORTS:
        raise ValueError(f"Unsupported shared-voice sort: {sort}")
    if page < 0:
        raise ValueError("page must be non-negative")
    params = {
        "page_size": PAGE_SIZE,
        "language": language,
        "category": category,
        "sort": sort,
        "page": page,
        "include_custom_rates": "true",
        "include_live_moderated": "false",
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    return _request_json(url, api_key)


def normalize_voice(raw: dict) -> dict | None:
    voice_id = raw.get("voice_id")
    name = raw.get("name")
    category = raw.get("category")
    if not isinstance(voice_id, str) or not voice_id.strip():
        return None
    if not isinstance(name, str) or not name.strip():
        return None
    # Do not ingest the provider's famous category into our discovery pool.
    if category not in ALLOWED_CATEGORIES:
        return None

    verified = raw.get("verified_languages")
    verified_languages = []
    if isinstance(verified, list):
        for entry in verified:
            if not isinstance(entry, dict):
                continue
            language = entry.get("language")
            if isinstance(language, str) and language.lower() in LANGUAGES:
                verified_languages.append({
                    "language": language.lower(),
                    "model_id": entry.get("model_id") if isinstance(entry.get("model_id"), str) else None,
                    "accent": entry.get("accent") if isinstance(entry.get("accent"), str) else None,
                    "locale": entry.get("locale") if isinstance(entry.get("locale"), str) else None,
                })

    raw_language = raw.get("language")
    language = raw_language.lower() if isinstance(raw_language, str) and raw_language.lower() in LANGUAGES else None
    language_set = sorted(set(([language] if language else []) + [x["language"] for x in verified_languages]))

    def optional_string(key: str):
        value = raw.get(key)
        return value if isinstance(value, str) else None

    def optional_int(key: str):
        value = raw.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

    return {
        "voice_id": voice_id.strip(),
        "name": name.strip(),
        "category": category,
        "language": language,
        "languages": language_set,
        "accent": optional_string("accent"),
        "gender": optional_string("gender"),
        "age": optional_string("age"),
        "descriptive": optional_string("descriptive"),
        "use_case": optional_string("use_case"),
        "description": optional_string("description"),
        "preview_url": optional_string("preview_url"),
        "featured": bool(raw.get("featured", False)),
        "free_users_allowed": raw.get("free_users_allowed") if isinstance(raw.get("free_users_allowed"), bool) else None,
        "live_moderation_enabled": raw.get("live_moderation_enabled") if isinstance(raw.get("live_moderation_enabled"), bool) else None,
        "usage_character_count_1y": optional_int("usage_character_count_1y"),
        "usage_character_count_7d": optional_int("usage_character_count_7d"),
        "play_api_usage_character_count_1y": optional_int("play_api_usage_character_count_1y"),
        "cloned_by_count": optional_int("cloned_by_count"),
        "rate": raw.get("rate") if isinstance(raw.get("rate"), (int, float)) else None,
        "verified_languages": verified_languages,
        "discovery_ranks": [],
    }


def collect_catalog(
    languages: list[str],
    pages_per_query: int,
    fetcher: Callable[..., dict] = fetch_shared_voices,
    api_key: str | None = None,
) -> tuple[list[dict], list[dict]]:
    if not 1 <= pages_per_query <= MAX_PAGES:
        raise ValueError(f"pages_per_query must be between 1 and {MAX_PAGES}")
    if not languages or any(language not in LANGUAGES for language in languages):
        raise ValueError("languages must contain vi and/or en")
    by_id: dict[str, dict] = {}
    query_report: list[dict] = []

    for language in languages:
        for category in ALLOWED_CATEGORIES:
            for sort in SORTS:
                pages_fetched = 0
                has_more = False
                for page in range(pages_per_query):
                    payload = fetcher(
                        language=language, category=category, sort=sort, page=page, api_key=api_key,
                    )
                    records = payload.get("voices", [])
                    if not isinstance(records, list):
                        raise RuntimeError("ElevenLabs shared-voices response has no voices array")
                    pages_fetched += 1
                    for rank_on_page, raw in enumerate(records, 1):
                        if not isinstance(raw, dict):
                            continue
                        voice = normalize_voice(raw)
                        if voice is None or language not in voice["languages"]:
                            continue
                        existing = by_id.setdefault(voice["voice_id"], voice)
                        existing["languages"] = sorted(set(existing["languages"]) | set(voice["languages"]))
                        existing["verified_languages"] = sorted(
                            {json.dumps(item, sort_keys=True): item
                             for item in existing["verified_languages"] + voice["verified_languages"]}.values(),
                            key=lambda item: (item["language"], item["locale"] or "", item["model_id"] or ""),
                        )
                        for key in (
                            "usage_character_count_1y", "usage_character_count_7d",
                            "play_api_usage_character_count_1y", "cloned_by_count",
                        ):
                            if voice[key] is not None:
                                existing[key] = max(existing[key] or 0, voice[key])
                        existing["featured"] = existing["featured"] or voice["featured"]
                        existing["discovery_ranks"].append({
                            "language_query": language,
                            "category_query": category,
                            "sort": sort,
                            "rank": page * PAGE_SIZE + rank_on_page,
                        })
                    has_more = bool(payload.get("has_more", False))
                    if not has_more:
                        break
                query_report.append({
                    "language": language,
                    "category": category,
                    "sort": sort,
                    "pages_fetched": pages_fetched,
                    "has_more_after_page_cap": has_more and pages_fetched >= pages_per_query,
                })

    voices = list(by_id.values())
    for voice in voices:
        voice["discovery_ranks"].sort(key=lambda row: (row["language_query"], row["category_query"], row["sort"], row["rank"]))
        voice["adoption_signals"] = {
            "usage_character_count_1y": voice["usage_character_count_1y"],
            "usage_character_count_7d": voice["usage_character_count_7d"],
            "cloned_by_count": voice["cloned_by_count"],
            "interpretation": "provider-reported marketplace adoption signals; not listener quality scores",
        }
    voices.sort(
        key=lambda row: (
            -int(row["usage_character_count_1y"] or 0),
            -int(row["cloned_by_count"] or 0),
            -int(row["usage_character_count_7d"] or 0),
            row["name"].casefold(),
        )
    )
    return voices, query_report


def make_html(voices: list[dict], built_at: str) -> str:
    cards = []
    for voice in voices:
        preview = voice.get("preview_url")
        preview_html = (
            f'<audio controls preload="none" src="{html.escape(preview, quote=True)}"></audio>'
            if preview and preview.startswith("https://") else "<p>No preview URL supplied.</p>"
        )
        metrics = (
            f"1y usage: {voice.get('usage_character_count_1y') or 'n/a'} · "
            f"7d usage: {voice.get('usage_character_count_7d') or 'n/a'} · "
            f"cloned by: {voice.get('cloned_by_count') or 'n/a'}"
        )
        cards.append(
            '<article class="voice">'
            f'<h2>{html.escape(voice["name"])}</h2>'
            f'<p class="meta">{html.escape(voice["category"])} · '
            f'{html.escape(", ".join(voice["languages"]) or "language unverified")}'
            f'{(" · " + html.escape(voice.get("accent") or "")) if voice.get("accent") else ""}</p>'
            f'<p>{html.escape(voice.get("description") or voice.get("descriptive") or "")}</p>'
            f'<p class="metrics">{html.escape(metrics)}</p>'
            f'{preview_html}'
            f'<p><code>{html.escape(voice["voice_id"])}</code></p>'
            '</article>'
        )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VoiceStudio · ElevenLabs shared voice discovery</title>
<style>
:root{{color-scheme:light dark;font:15px/1.55 system-ui,sans-serif}}
body{{max-width:1200px;margin:auto;padding:24px}}
header{{border-bottom:1px solid #8888;padding-bottom:18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin-top:20px}}
.voice{{border:1px solid #8888;border-radius:14px;padding:16px;min-width:0}}
.meta,.metrics{{opacity:.75;font-size:.85rem}}audio{{width:100%;margin:8px 0}}
code{{overflow-wrap:anywhere}}.notice{{border:1px solid #8888;border-radius:10px;padding:12px}}
</style></head><body><header><h1>ElevenLabs shared voice discovery</h1>
<p>Built {html.escape(built_at)} · {len(voices)} unique public shared voices</p>
<p class="notice">Popularity signals are not audio-quality scores. Voices remain hosted and controlled by ElevenLabs and their owners. Do not copy, clone, rehost, or imitate a named person; use each shared voice only under the provider's current access and commercial terms. The famous category is deliberately excluded.</p>
</header><main class="grid">{''.join(cards)}</main></body></html>"""


def write_catalog(output: Path, languages: list[str], pages_per_query: int, api_key: str | None) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    voices, queries = collect_catalog(languages, pages_per_query, api_key=api_key)
    built_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    catalog = {
        "schema_version": 1,
        "source": "ElevenLabs public shared-voice marketplace",
        "source_endpoint": API_URL,
        "documentation": DOCS_URL,
        "built_at": built_at,
        "languages_requested": languages,
        "categories_included": list(ALLOWED_CATEGORIES),
        "categories_excluded": ["famous"],
        "sort_signals": list(SORTS),
        "pages_per_query": pages_per_query,
        "unique_voice_count": len(voices),
        "query_report": queries,
        "policy": {
            "asset_type": "provider-hosted marketplace metadata; not copied audio assets",
            "rights": "This catalog does not grant independent rights to download, bundle, rehost, clone, train on, or redistribute voice assets. Respect provider, voice-owner, and plan terms.",
            "popularity": "usage_character_count and cloned_by_count are provider-reported adoption signals, not listener preference or voice-quality scores.",
            "quality_gate": "Every candidate still requires native-language blind listening, pronunciation checks, long-form stability checks, and rights review before production promotion.",
            "identity_safety": "Famous category is excluded; never imitate a celebrity, public figure, creator, or identifiable person without explicit authorization.",
        },
        "voices": voices,
    }
    (output / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    (output / "index.html").write_text(make_html(voices, built_at), encoding="utf-8")
    readme = f"""# ElevenLabs shared voice discovery

- Unique provider-hosted shared voices found: {len(voices)}
- Languages requested: {", ".join(languages)}
- Categories included: {", ".join(ALLOWED_CATEGORIES)}
- Categories excluded: famous
- Built: {built_at}

This is a metadata-only discovery snapshot. It does not generate, download, clone,
or redistribute audio. Open index.html to audition preview URLs supplied by the
provider. Use voice IDs only through an account and plan authorized by ElevenLabs.

usage_character_count_1y, usage_character_count_7d, and cloned_by_count are
marketplace adoption signals, not quality ratings or proof of external
creator/channel deployments. Native-language blind listening and rights review
are required before recommending or promoting any voice.

Official endpoint: {API_URL}
Documentation: {DOCS_URL}
"""
    (output / "README.md").write_text(readme, encoding="utf-8")
    return catalog


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("both", "vi", "en"), default="both")
    parser.add_argument("--pages-per-query", type=int, default=2)
    parser.add_argument("--output", default="dist/elevenlabs-shared-voices")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.pages_per_query <= MAX_PAGES:
        raise SystemExit(f"--pages-per-query must be between 1 and {MAX_PAGES}")
    languages = list(LANGUAGES) if args.language == "both" else [args.language]
    api_key = os.environ.get("ELEVENLABS_API_KEY") or None
    try:
        catalog = write_catalog(Path(args.output), languages, args.pages_per_query, api_key)
    except Exception as exc:
        print(f"[elevenlabs-discovery] ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    incomplete = sum(1 for row in catalog["query_report"] if row["has_more_after_page_cap"])
    print(
        f"[elevenlabs-discovery] COMPLETE {catalog['unique_voice_count']} unique voices; "
        f"{len(catalog['query_report'])} queries; {incomplete} query page caps reached",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
