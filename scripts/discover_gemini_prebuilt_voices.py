#!/usr/bin/env python3
"""Discover Google's public prebuilt Gemini TTS voice catalog.

This fetches provider-hosted metadata only. It does not synthesize audio,
retrieve private user-created voices, clone speakers, or redistribute assets.
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

API_URL = "https://generativelanguage.googleapis.com/v1beta/voices"
DOCS_URL = "https://ai.google.dev/api/voices"
TTS_DOCS_URL = "https://ai.google.dev/gemini-api/docs/speech-generation"
SUPPORTED_LANGUAGES = ("vi", "en")
PAGE_SIZE = 1000
MAX_PAGES = 10
USER_AGENT = "VoiceStudio-GeminiVoiceDiscovery/1.0"


def request_json(url: str, api_key: str, timeout: int = 30) -> dict:
    if not api_key or not api_key.strip():
        raise ValueError("GEMINI_API_KEY is required for the Google Voices API")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "x-goog-api-key": api_key,
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
                if len(payload) > 20 * 1024 * 1024:
                    raise RuntimeError("Google Voice Library response exceeded 20 MiB safety limit")
                result = json.loads(payload.decode("utf-8"))
                if not isinstance(result, dict):
                    raise RuntimeError("Google ListVoices response must be a JSON object")
                return result
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
            detail = exc.read(1600).decode("utf-8", errors="replace")
            raise RuntimeError(f"Google ListVoices returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < 3:
                time.sleep(float(2 ** attempt))
                continue
            raise RuntimeError(f"Google Voice Library request failed: {exc}") from exc
    raise RuntimeError("Google ListVoices retries were exhausted")


def list_prebuilt_voices(api_key: str, page_token: str | None = None) -> dict:
    params = [("page_size", str(PAGE_SIZE)), ("type", "prebuilt")]
    if page_token:
        params.append(("page_token", page_token))
    return request_json(f"{API_URL}?{urllib.parse.urlencode(params)}", api_key)


def normalize_voice(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    voice_id = raw.get("id")
    voice_type = raw.get("type")
    display_name = raw.get("display_name")
    if not isinstance(voice_id, str) or not voice_id.strip():
        return None
    # Never publish a user's custom, replicated, or prompted voice identifier.
    if not isinstance(voice_type, str) or voice_type.lower() != "prebuilt":
        return None

    def optional_text(key: str) -> str | None:
        value = raw.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    language_code = optional_text("language_code")
    language = language_code.lower().split("-", 1)[0] if language_code else None
    if language not in SUPPORTED_LANGUAGES:
        return None

    return {
        "voice_id": voice_id.strip(),
        "display_name": display_name.strip() if isinstance(display_name, str) and display_name.strip() else voice_id.strip(),
        "type": "prebuilt",
        "model": optional_text("model"),
        "language_code": language_code,
        "language": language,
        "region_code": optional_text("region_code"),
        "accent": optional_text("accent"),
        "persona": optional_text("persona"),
        "context": optional_text("context"),
        "gender": optional_text("gender"),
        "pitch": optional_text("pitch"),
        "description": optional_text("description"),
    }


def collect_catalog(api_key: str, max_pages: int = MAX_PAGES, fetcher=list_prebuilt_voices) -> tuple[list[dict], dict]:
    if not 1 <= max_pages <= MAX_PAGES:
        raise ValueError(f"max_pages must be between 1 and {MAX_PAGES}")
    by_id: dict[str, dict] = {}
    page_token = None
    pages_fetched = 0
    has_more = False
    while pages_fetched < max_pages:
        payload = fetcher(api_key, page_token)
        rows = payload.get("voices", [])
        if not isinstance(rows, list):
            raise RuntimeError("Google ListVoices response has no voices array")
        pages_fetched += 1
        for raw in rows:
            voice = normalize_voice(raw)
            if voice is not None:
                by_id.setdefault(voice["voice_id"], voice)
        page_token = payload.get("next_page_token")
        has_more = bool(page_token)
        if not has_more:
            break

    voices = sorted(
        by_id.values(),
        key=lambda row: (
            row["language"],
            row["language_code"].casefold(),
            (row.get("accent") or "").casefold(),
            (row.get("persona") or "").casefold(),
            row["display_name"].casefold(),
        ),
    )
    report = {
        "pages_fetched": pages_fetched,
        "page_size": PAGE_SIZE,
        "max_pages": max_pages,
        "has_more_after_page_cap": has_more and pages_fetched >= max_pages,
        "unique_prebuilt_voices": len(voices),
        "language_counts": {
            language: sum(1 for voice in voices if voice["language"] == language)
            for language in SUPPORTED_LANGUAGES
        },
    }
    return voices, report


def make_html(voices: list[dict], built_at: str) -> str:
    cards = []
    for voice in voices:
        details = [
            voice.get("language_code"),
            voice.get("accent"),
            voice.get("persona"),
            voice.get("context"),
            voice.get("gender"),
            voice.get("pitch"),
        ]
        labels = " · ".join(html.escape(value) for value in details if value)
        description = html.escape(voice.get("description") or "")
        cards.append(
            '<article class="voice">'
            f'<h2>{html.escape(voice["display_name"])}</h2>'
            f'<p class="meta">{labels}</p>'
            f'<p>{description}</p>'
            f'<code>{html.escape(voice["voice_id"])}</code>'
            '</article>'
        )
    language_counts = {
        language: sum(1 for voice in voices if voice["language"] == language)
        for language in SUPPORTED_LANGUAGES
    }
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VoiceStudio · Google Gemini prebuilt voice discovery</title>
<style>
:root{{color-scheme:light dark;font:15px/1.55 system-ui,sans-serif}}
body{{max-width:1200px;margin:auto;padding:24px}}
header{{border-bottom:1px solid #8888;padding-bottom:18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:14px;margin-top:20px}}
.voice{{border:1px solid #8888;border-radius:14px;padding:16px;min-width:0}}
.meta{{opacity:.75;font-size:.85rem}}code{{overflow-wrap:anywhere}}
.notice{{border:1px solid #8888;border-radius:10px;padding:12px}}
</style></head><body><header>
<h1>Google Gemini prebuilt voice catalog</h1>
<p>Built {html.escape(built_at)} · {len(voices)} unique VI/EN prebuilt voices</p>
<p>Vietnamese: {language_counts["vi"]} · English: {language_counts["en"]}</p>
<p class="notice">Metadata-only catalog. ListVoices does not return preview audio for prebuilt voices. No audio was generated, no user-created/replicated voices were exported, and voice IDs remain Google-managed. Test each candidate through an authorized Gemini 3.8 TTS account before production use.</p>
</header><main class="grid">{''.join(cards)}</main></body></html>"""


def write_catalog(output: Path, api_key: str, max_pages: int = MAX_PAGES) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    voices, report = collect_catalog(api_key, max_pages)
    built_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    catalog = {
        "schema_version": 1,
        "source": "Google Gemini Voices API prebuilt catalog",
        "source_endpoint": API_URL,
        "documentation": DOCS_URL,
        "tts_documentation": TTS_DOCS_URL,
        "built_at": built_at,
        "models": ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts"],
        "voice_type_filter": "prebuilt",
        "language_scope": list(SUPPORTED_LANGUAGES),
        "report": report,
        "policy": {
            "asset_type": "Google-managed prebuilt voice metadata; not audio assets",
            "rights": "This snapshot does not grant independent rights to download, bundle, clone, train on, or redistribute voice assets. Use only through Google-authorized API access and current provider terms.",
            "privacy": "Only type=prebuilt results are included. Caller-owned prompted/replicated voice IDs are intentionally excluded from the public catalog.",
            "preview": "ListVoices does not return sample_audio for prebuilt voices. This workflow generates no audio.",
            "quality_gate": "Voice metadata and language tags do not establish naturalness. Native-language blind listening, pronunciation checks and long-form stability checks are required before promotion.",
        },
        "voices": voices,
    }
    (output / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "index.html").write_text(make_html(voices, built_at), encoding="utf-8")
    (output / "README.md").write_text(
        "# Google Gemini prebuilt voice discovery\n\n"
        f"- Unique VI/EN prebuilt voices: {len(voices)}\n"
        f"- Vietnamese: {report['language_counts']['vi']}\n"
        f"- English: {report['language_counts']['en']}\n"
        f"- Pages fetched: {report['pages_fetched']}\n"
        f"- Page cap reached: {report['has_more_after_page_cap']}\n"
        f"- Built: {built_at}\n\n"
        "This workflow reads the provider-hosted prebuilt voice catalog only. It does not synthesize, "
        "download preview audio, export caller-owned replicated/prompted voices, or grant independent redistribution rights. "
        "Use Gemini 3.8 Flash TTS for maximum fidelity/expressivity and Gemini 3.8 Flash-Lite TTS for throughput; "
        "benchmark actual voices separately in Vietnamese and English.\n\n"
        f"API: {API_URL}\nDocs: {DOCS_URL}\nTTS models: {TTS_DOCS_URL}\n",
        encoding="utf-8",
    )
    return catalog


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    parser.add_argument("--output", default="dist/gemini-prebuilt-voices")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = os.environ.get("GEMINI_API_KEY")
    try:
        catalog = write_catalog(Path(args.output), api_key or "", args.max_pages)
    except Exception as exc:
        print(f"[gemini-voice-discovery] ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        f"[gemini-voice-discovery] COMPLETE {catalog['report']['unique_prebuilt_voices']} "
        f"voices; VI={catalog['report']['language_counts']['vi']}; "
        f"EN={catalog['report']['language_counts']['en']}; "
        f"page_cap={catalog['report']['has_more_after_page_cap']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
