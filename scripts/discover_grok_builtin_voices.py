#!/usr/bin/env python3
"""Discover xAI provider-managed built-in Grok TTS voices (metadata only).

Calls GET /v1/tts/voices. It never calls GET /v1/custom-voices and never
generates audio or exports user-owned custom voice identifiers.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_URL = "https://api.x.ai/v1/tts/voices"
DOCS_URL = "https://docs.x.ai/developers/model-capabilities/audio/text-to-speech"
VOICE_OVERVIEW_URL = "https://docs.x.ai/developers/model-capabilities/audio/voice"
SUPPORTED_LANGUAGES = ("vi", "en")
PRICE_PER_MILLION_CHARACTERS_USD = 15.0
USER_AGENT = "VoiceStudio-GrokVoiceDiscovery/1.0"

VOICE_PROFILES = {
    "carina": {"tone": "soft, empathetic, soothing", "use_cases": ["wellness", "support"]},
    "zagan": {"tone": "powerful, dramatic", "use_cases": ["characters", "narration"]},
    "helix": {"tone": "bold, dynamic", "use_cases": ["commentary", "podcast"]},
    "orion": {"tone": "rich, cinematic, resonant", "use_cases": ["narration", "audiobooks"]},
    "luna": {"tone": "gentle, patient, nurturing", "use_cases": ["education", "assistant"]},
    "iris": {"tone": "friendly, upbeat, charming", "use_cases": ["sales", "support"]},
    "altair": {"tone": "elegant, refined, premium", "use_cases": ["advertising", "narration"]},
    "zenith": {"tone": "sharp, focused, driven", "use_cases": ["sales", "advertising"]},
    "perseus": {"tone": "strong, confident, trustworthy", "use_cases": ["advertising", "narration"]},
    "helios": {"tone": "upbeat, energetic, versatile", "use_cases": ["assistant", "wellness"]},
    "lux": {"tone": "grounded, calm, wise", "use_cases": ["wellness", "narration"]},
    "kepler": {"tone": "inventive, forward-thinking, charismatic", "use_cases": ["advertising", "podcast"]},
    "rigel": {"tone": "precise, professional, calmly confident", "use_cases": ["assistant", "support"]},
    "cosmo": {"tone": "bright, curious, easy to follow", "use_cases": ["education", "podcast"]},
    "celeste": {"tone": "compassionate, confident, reassuring", "use_cases": ["support", "assistant"]},
    "ursa": {"tone": "friendly, warm, steadfast", "use_cases": ["assistant", "podcast"]},
    "sirius": {"tone": "quick-witted, clever, playful", "use_cases": ["commentary", "characters"]},
    "lumen": {"tone": "warm, articulate, engaging", "use_cases": ["education", "advertising"]},
    "castor": {"tone": "charismatic, down-to-earth, easygoing", "use_cases": ["sales", "support"]},
    "naksh": {"tone": "warm, thoughtful, wise", "use_cases": ["assistant", "support"]},
    "atlas": {"tone": "confident, commanding, reassuring", "use_cases": ["sales", "assistant"]},
    "ara": {"tone": "warm and friendly", "use_cases": ["general"]},
    "eve": {"tone": "energetic and upbeat", "use_cases": ["general"]},
    "leo": {"tone": "authoritative and strong", "use_cases": ["general"]},
    "rex": {"tone": "confident and clear", "use_cases": ["general"]},
    "sal": {"tone": "smooth and balanced", "use_cases": ["general"]},
}


def request_json(url: str, api_key: str, timeout: int = 30) -> dict:
    if not api_key or not api_key.strip():
        raise ValueError("XAI_API_KEY is required for the built-in voice list endpoint")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                if len(body) > 4 * 1024 * 1024:
                    raise RuntimeError("xAI built-in voice response exceeded 4 MiB safety limit")
                payload = json.loads(body.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise RuntimeError("xAI List TTS Voices response must be a JSON object")
                return payload
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if retryable and attempt < 3:
                retry_after = exc.headers.get("Retry-After", "")
                try:
                    delay = min(20.0, max(1.0, float(retry_after)))
                except (ValueError, TypeError):
                    delay = float(2 ** attempt)
                time.sleep(delay)
                continue
            detail = exc.read(1200).decode("utf-8", errors="replace")
            raise RuntimeError(f"xAI List TTS Voices returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < 3:
                time.sleep(float(2 ** attempt))
                continue
            raise RuntimeError(f"xAI built-in voice list request failed: {exc}") from exc
    raise RuntimeError("xAI built-in voice list retries were exhausted")


def list_builtin_voices(api_key: str) -> dict:
    return request_json(API_URL, api_key)


def normalize_voice(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    voice_id = raw.get("voice_id")
    name = raw.get("name")
    if not isinstance(voice_id, str) or not voice_id.strip():
        return None
    if not isinstance(name, str) or not name.strip():
        return None
    voice_id = voice_id.strip().lower()
    if len(voice_id) > 64 or not voice_id.replace("-", "").replace("_", "").isalnum():
        return None
    language_value = raw.get("language")
    language = language_value.strip().lower() if isinstance(language_value, str) else None
    if language not in {"multilingual", "multi", "all", None, ""}:
        if language not in SUPPORTED_LANGUAGES:
            return None
    profile = VOICE_PROFILES.get(voice_id, {})
    return {
        "voice_id": voice_id,
        "name": name.strip(),
        "language_scope": ["vi", "en"] if language in {"multilingual", "multi", "all", None, ""} else [language],
        "provider_language": language or "multilingual",
        "kind": "provider_managed_builtin",
        "tone": profile.get("tone"),
        "use_cases": profile.get("use_cases", []),
        "voice_profile_source": VOICE_OVERVIEW_URL if profile else None,
    }


def collect_catalog(api_key: str, fetcher=request_json) -> list[dict]:
    payload = fetcher(API_URL, api_key)
    rows = payload.get("voices")
    if not isinstance(rows, list):
        raise RuntimeError("xAI List TTS Voices response has no voices array")
    by_id: dict[str, dict] = {}
    for raw in rows:
        voice = normalize_voice(raw)
        if voice is not None:
            by_id.setdefault(voice["voice_id"], voice)
    return sorted(by_id.values(), key=lambda voice: voice["voice_id"])


def make_html(voices: list[dict], built_at: str) -> str:
    cards = []
    for voice in voices:
        languages = ", ".join(voice["language_scope"]).upper()
        tone = voice.get("tone") or "Provider description not listed"
        cases = ", ".join(voice.get("use_cases", [])) or "general"
        cards.append(
            '<article class="voice">'
            f'<h2>{html.escape(voice["name"])}</h2>'
            f'<p class="id"><code>{html.escape(voice["voice_id"])}</code></p>'
            f'<p class="meta">{html.escape(languages)} · {html.escape(cases)}</p>'
            f'<p>{html.escape(tone)}</p></article>'
        )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VoiceStudio · Grok built-in voice catalogue</title>
<style>
:root{{color-scheme:light dark;font:15px/1.55 system-ui,sans-serif}}
body{{max-width:1160px;margin:auto;padding:24px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;margin-top:20px}}
.voice{{border:1px solid #8888;border-radius:14px;padding:16px;min-width:0}}
.meta,.id{{opacity:.7;font-size:.85rem}}code{{overflow-wrap:anywhere}}
.notice{{border:1px solid #8888;border-radius:10px;padding:12px}}
</style></head><body><header>
<h1>Grok built-in TTS voices</h1>
<p>{len(voices)} provider-managed built-in voices · built {html.escape(built_at)}</p>
<p class="notice">This index uses only GET /v1/tts/voices. Custom voices are stored in a separate provider endpoint and are intentionally not queried or exposed. All listed built-in voices can be used with Vietnamese and English through authorized xAI API access; language support does not guarantee equal pronunciation quality. No audio was generated.</p>
</header><main class="grid">{''.join(cards)}</main></body></html>"""


def write_catalog(output: Path, api_key: str) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    voices = collect_catalog(api_key)
    built_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    catalog = {
        "schema_version": 1,
        "provider": "xAI",
        "kind": "provider_managed_builtin_tts_voices",
        "source_endpoint": API_URL,
        "documentation": DOCS_URL,
        "voice_profile_documentation": VOICE_OVERVIEW_URL,
        "built_at": built_at,
        "language_scope": list(SUPPORTED_LANGUAGES),
        "supported_language_count": 20,
        "price_per_million_input_characters_usd": PRICE_PER_MILLION_CHARACTERS_USD,
        "custom_voice_endpoint_excluded": "https://api.x.ai/v1/custom-voices",
        "voice_count": len(voices),
        "policy": {
            "asset_type": "provider-managed built-in voice IDs and metadata only",
            "privacy": "Only GET /v1/tts/voices is called. GET /v1/custom-voices is intentionally excluded because it contains user-owned/custom voice identities.",
            "rights": "This catalogue does not grant independent rights to download, copy, rehost, clone, or redistribute provider voices or audio. Use only through authorized xAI access and current provider terms.",
            "languages": "The official API lists Vietnamese (vi) and English (en) among 20 supported BCP-47 language codes and states any built-in voice can speak each supported language.",
            "quality": "A built-in voice ID is not a human quality score. Every candidate still requires matched Vietnamese and English blind listening, locale pronunciation and long-form stability checks.",
            "popularity": "The built-in voice endpoint has no adoption counters; VoiceStudio does not label these voices popular or infer usage from provider default order.",
        },
        "voices": voices,
    }
    (output / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "index.html").write_text(make_html(voices, built_at), encoding="utf-8")
    (output / "README.md").write_text(
        "# Grok built-in TTS voice discovery\n\n"
        f"- Built-in voices returned: {len(voices)}\n"
        "- Vietnamese and English supported by the provider for all built-in voices\n"
        "- Custom-voice endpoint queried: no\n"
        "- Audio generation requests made: 0\n"
        f"- Built: {built_at}\n\n"
        "Voice IDs are provider-managed metadata. The endpoint exposes no adoption counters, so this catalogue is a verified inventory, not a popularity ranking. Listen to each voice in both languages before choosing one for production.\n\n"
        f"List endpoint: {API_URL}\nTTS docs: {DOCS_URL}\nVoice overview: {VOICE_OVERVIEW_URL}\n",
        encoding="utf-8",
    )
    return catalog


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="dist/grok-builtin-voices")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = os.environ.get("XAI_API_KEY")
    output = Path(args.output)
    if not api_key:
        output.mkdir(parents=True, exist_ok=True)
        (output / "README.md").write_text(
            "# Grok built-in voice discovery not executed\n\n"
            "The xAI List TTS Voices endpoint requires the repository Actions secret XAI_API_KEY. "
            "No audio was generated and no paid TTS call was sent. Configure the secret and rerun this workflow.\n",
            encoding="utf-8",
        )
        print("[grok-voice-discovery] SKIPPED: XAI_API_KEY is not configured; no API request sent.")
        return 0
    try:
        catalog = write_catalog(output, api_key)
    except Exception as exc:
        print(f"[grok-voice-discovery] ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"[grok-voice-discovery] COMPLETE {catalog['voice_count']} provider-managed built-in voices; no audio generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
