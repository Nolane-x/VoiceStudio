#!/usr/bin/env python3
"""Build deterministic synthetic voice-design blueprints for Vietnamese and English.

This creates descriptions and preview prompts only. It does not render or register
voices, call a provider API, claim speaker identities, or spend credits.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

DEFAULT_MODEL_BY_LANGUAGE = {
    "vi": "eleven_ttv_v3",
    "en": "eleven_multilingual_ttv_v2",
}

SAMPLE_TEXT = {
    "vi": (
        "Xin chào, hôm nay chúng ta sẽ cùng khám phá một câu chuyện mới. "
        "Năm 2026, công nghệ thay đổi rất nhanh, nhưng một giọng đọc tốt vẫn cần "
        "phát âm đủ sáu thanh điệu, ngắt nghỉ tự nhiên và giữ cảm xúc chân thật. "
        "Hãy lắng nghe thật kỹ, vì những chi tiết nhỏ thường tạo nên khác biệt lớn."
    ),
    "en": (
        "Hello, and welcome. Today we are exploring a new idea: how technology, "
        "creativity, and everyday stories shape the way we understand the world. "
        "A great narrator sounds clear, natural, and easy to follow, with thoughtful "
        "pauses, expressive phrasing, and a confident finish."
    ),
}

ACCENTS = {
    "vi": [
        ("north-hanoi", "Northern Vietnamese, contemporary Hanoi standard", "Speak natural Vietnamese with a contemporary Hanoi/Northern accent."),
        ("north-coastal", "Northern Vietnamese, coastal variety", "Use a natural Northern coastal Vietnamese accent, while keeping standard, widely intelligible pronunciation."),
        ("central-hue", "Central Vietnamese, Hue-influenced", "Use a gentle Central Vietnamese accent influenced by Hue, preserving clear and intelligible tones."),
        ("central-general", "Central Vietnamese, neutral regional variety", "Use a natural Central Vietnamese accent with measured, clearly articulated tones."),
        ("south-saigon", "Southern Vietnamese, Ho Chi Minh City standard", "Speak with a contemporary Southern Vietnamese accent associated with Ho Chi Minh City."),
        ("south-mekong", "Southern Vietnamese, Mekong Delta variety", "Use a warm Mekong Delta/Southern Vietnamese accent, while remaining easy for a broad audience to understand."),
    ],
    "en": [
        ("us-general", "General American English", "Speak General American English with stable, natural pronunciation."),
        ("uk-modern", "Modern Southern British English", "Speak modern Southern British English, natural and contemporary rather than theatrical."),
        ("australian-general", "General Australian English", "Speak General Australian English with a natural, conversational delivery."),
        ("canadian-general", "General Canadian English", "Speak General Canadian English with clear, neutral pronunciation."),
        ("indian-urban", "Indian English, educated urban variety", "Speak clear, contemporary Indian English with natural local rhythm, not an exaggerated accent."),
    ],
}

DIMENSIONS = {
    "presentation": [
        ("feminine", "feminine vocal presentation"),
        ("masculine", "masculine vocal presentation"),
        ("androgynous", "androgynous, gender-neutral vocal presentation"),
    ],
    "perceived_age": [
        ("young-adult", "young adult vocal quality"),
        ("mature-adult", "mature adult vocal quality"),
        ("older-adult", "older adult vocal quality"),
    ],
    "timbre": [
        ("warm-rounded", "warm, rounded timbre"),
        ("bright-clear", "bright, clear timbre"),
        ("rich-resonant", "rich, resonant timbre"),
        ("soft-airy", "soft, lightly airy timbre"),
        ("smooth-polished", "smooth, polished timbre"),
        ("light-agile", "light, agile timbre"),
        ("full-bodied", "full-bodied, cinematic timbre"),
        ("gently-textured", "subtly textured timbre with a natural vocal grain"),
    ],
    "use_case": [
        ("documentary", "documentary narration"),
        ("educational", "educational explanation"),
        ("audiobook", "long-form audiobook storytelling"),
        ("podcast", "conversational podcast hosting"),
        ("short-form", "short-form social video narration"),
        ("corporate", "professional corporate explanation"),
        ("news", "clear informational and news-style presentation"),
        ("wellness", "calm wellness and reflective narration"),
    ],
    "pitch": [
        ("low", "lower pitch range"),
        ("mid-low", "mid-low pitch range"),
        ("mid", "middle pitch range"),
        ("mid-high", "mid-high pitch range"),
    ],
    "pace": [
        ("measured", "measured pace with thoughtful pauses"),
        ("conversational", "steady conversational pace"),
        ("brisk-clear", "brisk but clearly articulated pace"),
        ("expressive", "expressive pacing with controlled variation"),
    ],
    "delivery": [
        ("warm-assured", "warm, reassuring delivery"),
        ("curious-engaging", "curious, engaging delivery"),
        ("calm-authoritative", "calm, quietly authoritative delivery"),
        ("upbeat-optimistic", "upbeat, optimistic delivery without overacting"),
    ],
}

MARKET_ARCHETYPES = {
    "documentary": [
        ("cinematic-documentary", "Cinematic documentary narrator", "Use composed authority, vivid but restrained storytelling, and patient sentence endings."),
        ("warm-history-storyteller", "Warm history storyteller", "Sound inviting and knowledgeable, with a warm narrative arc and measured emphasis."),
    ],
    "educational": [
        ("friendly-educator", "Friendly educator", "Explain ideas clearly and patiently, with encouraging emphasis and accessible phrasing."),
        ("expert-explainer", "Clear expert explainer", "Sound precise and confident without becoming stiff, rushed, or overly academic."),
    ],
    "audiobook": [
        ("immersive-audiobook", "Immersive audiobook performer", "Use expressive but controlled storytelling, character-neutral dialogue, and consistent long-form pacing."),
        ("reflective-storyteller", "Reflective long-form storyteller", "Create an intimate, attentive narrative flow with natural pauses and emotional restraint."),
    ],
    "podcast": [
        ("conversational-host", "Conversational podcast host", "Sound engaging and spontaneous while maintaining clean articulation and stable loudness."),
        ("curious-interviewer", "Curious interview host", "Use attentive, warm phrasing and natural conversational turns without impersonating a real host."),
    ],
    "short-form": [
        ("creator-hook", "High-retention short-form creator narrator", "Open with a crisp, natural hook; keep energy lively while preserving intelligibility."),
        ("energetic-social", "Energetic social-video narrator", "Use upbeat rhythm, clear phrase boundaries, and a memorable but non-theatrical finish."),
    ],
    "corporate": [
        ("professional-presenter", "Polished professional presenter", "Sound trustworthy, concise, and confident, with neutral emphasis and clear transitions."),
        ("premium-brand", "Premium brand storyteller", "Use smooth, refined delivery and understated confidence rather than exaggerated luxury styling."),
    ],
    "news": [
        ("credible-news-anchor", "Credible news anchor", "Use controlled authority, clean diction, balanced pace, and neutral factual delivery."),
        ("journalistic-explainer", "Journalistic explainer", "Make complex information approachable with clear stress and carefully placed pauses."),
    ],
    "wellness": [
        ("calm-wellness-guide", "Calm wellness guide", "Use gentle pacing, reassuring warmth, and natural breathing without whispering or sounding sleepy."),
        ("mindful-reflection", "Mindful reflection narrator", "Use quiet confidence, soft phrase endings, and thoughtful pauses without artificial sentimentality."),
    ],
}

def _stable_seed(profile_id: str, dimensions: dict[str, str], used: set[int]) -> int:
    canonical = json.dumps(dimensions, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    salt = 0
    while True:
        raw = hashlib.sha256(f"{profile_id}|{canonical}|{salt}".encode("utf-8")).digest()
        seed = int.from_bytes(raw[:4], "big") & 0x7FFFFFFF
        if seed not in used:
            used.add(seed)
            return seed
        salt += 1


def _voice_description(language: str, accent: tuple[str, str, str], dimensions: dict[str, str], archetype: tuple[str, str, str]) -> str:
    language_rule = (
        "Preserve all six Vietnamese tones, clear final consonants, natural sentence melody, "
        "and the target regional pronunciation."
        if language == "vi"
        else "Use accurate English vowels, clear consonants, stable accent placement, "
             "and natural sentence stress."
    )
    return (
        f"Create an original {'Vietnamese' if language == 'vi' else 'English'} synthetic voice. "
        f"Accent: {accent[1]}; {accent[2]} "
        f"Vocal profile: {dimensions['presentation']}, {dimensions['perceived_age']}, "
        f"{dimensions['timbre']}, {dimensions['pitch']} pitch. "
        f"Persona style: {archetype[1]}; {archetype[2]} "
        f"Delivery: {dimensions['delivery']}; pace: {dimensions['pace']}. "
        f"{language_rule} "
        "Do not imitate any real person, public figure, celebrity, creator, or copyrighted character."
    )


def build_profiles(language: str, per_language: int = 1000) -> list[dict[str, Any]]:
    if language not in SAMPLE_TEXT:
        raise ValueError(f"Unsupported language: {language}")
    if per_language < 1 or per_language > 5000:
        raise ValueError("per_language must be between 1 and 5000")

    accent_rows = ACCENTS[language]
    dimension_names = list(DIMENSIONS)
    value_rows = [DIMENSIONS[name] for name in dimension_names]
    combinations = []
    for accent, *dimension_values in itertools.product(accent_rows, *value_rows):
        dimensions = {
            name: value[0]
            for name, value in zip(dimension_names, dimension_values, strict=True)
        }
        combinations.append((accent, dimensions))

    if per_language > len(combinations):
        raise ValueError(f"Requested {per_language} profiles but only {len(combinations)} unique combinations exist")

    combinations.sort(
        key=lambda item: hashlib.sha256(
            (
                language + "|" + item[0][0] + "|" +
                json.dumps(item[1], sort_keys=True, separators=(",", ":"))
            ).encode("utf-8")
        ).digest()
    )

    used_seeds: set[int] = set()
    profiles = []
    locale_codes = {
        "vi": "vi-VN",
        "us-general": "en-US",
        "uk-modern": "en-GB",
        "australian-general": "en-AU",
        "canadian-general": "en-CA",
        "indian-urban": "en-IN",
    }
    archetype_counts = {use_case: 0 for use_case in MARKET_ARCHETYPES}
    for index, (accent, dimensions) in enumerate(combinations[:per_language], start=1):
        profile_id = f"{language}-{accent[0]}-{index:04d}"
        archetype_rows = MARKET_ARCHETYPES[dimensions["use_case"]]
        archetype_index = archetype_counts[dimensions["use_case"]] % len(archetype_rows)
        archetype_counts[dimensions["use_case"]] += 1
        archetype = archetype_rows[archetype_index]
        expanded = dict(dimensions)
        profiles.append({
            "profile_id": profile_id,
            "record_type": "voice_design_profile",
            "generation_state": "blueprint_only_not_a_rendered_voice",
            "language": language,
            "locale": locale_codes["vi"] if language == "vi" else locale_codes[accent[0]],
            "accent_id": accent[0],
            "accent_label": accent[1],
            "intended_use_case": dimensions["use_case"],
            "market_archetype_id": archetype[0],
            "market_archetype_label": archetype[1],
            "dimensions": expanded,
            "voice_description": _voice_description(language, accent, dimensions, archetype),
            "preview_text": SAMPLE_TEXT[language],
            "seed": _stable_seed(profile_id, expanded, used_seeds),
            "provider": "elevenlabs_voice_design",
            "model_id_default": DEFAULT_MODEL_BY_LANGUAGE[language],
            "identity_class": "original_synthetic_persona",
            "identity_rights": "no_real_person_reference_or_impersonation",
            "shareability": "not_shareable_to_public_elevenlabs_voice_library",
            "commercial_status": "provider_account_terms_and_plan_review_required",
            "human_review_required": True,
        })
    return profiles


def write_catalog(output: Path, language: str, per_language: int) -> dict[str, Any]:
    languages = ("vi", "en") if language == "both" else (language,)
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for lang in languages:
        records.extend(build_profiles(lang, per_language))

    jsonl_path = output / "profiles.jsonl"
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in records
    ).encode("utf-8")
    jsonl_path.write_bytes(payload)
    counts = {
        lang: sum(row["language"] == lang for row in records)
        for lang in ("vi", "en")
    }
    manifest = {
        "schema_version": 1,
        "catalog_type": "voice_design_blueprints",
        "record_type": "voice_design_profile",
        "is_rendered_voice_catalog": False,
        "total_profiles": len(records),
        "unique_rendered_voice_identities": 0,
        "profiles_by_language": counts,
        "market_archetype_count": sum(len(rows) for rows in MARKET_ARCHETYPES.values()),
        "profiles_by_market_archetype": {
            archetype[0]: sum(row["market_archetype_id"] == archetype[0] for row in records)
            for rows in MARKET_ARCHETYPES.values()
            for archetype in rows
        },
        "provider": "ElevenLabs Voice Design API",
        "default_models_by_language": DEFAULT_MODEL_BY_LANGUAGE,
        "profiles_file": jsonl_path.name,
        "profiles_sha256": hashlib.sha256(payload).hexdigest(),
        "profile_limit_per_language": per_language,
        "human_review_required": True,
        "paid_api_calls_performed": 0,
        "notice": (
            "These are original synthetic voice-design blueprints, not generated audio, "
            "saved provider voices, or verified speaker identities. API preview generation "
            "is a separate manually confirmed workflow."
        ),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "README.md").write_text(
        "# Voice Design Blueprint Catalog\n\n"
        f"This artifact contains {len(records):,} original synthetic design profiles "
        f"({counts['vi']:,} Vietnamese and {counts['en']:,} English).\n\n"
        "**Important:** these are prompt blueprints, not rendered voices. "
        "No API was called and no credits were spent to create this catalog. "
        "Profiles span 16 original creator-facing market archetypes. A separate manually dispatched workflow creates paid previews only after explicit confirmation.\n\n"
        "Every profile has a deterministic profile ID and seed, requested locale/accent, use case, "
        "vocal design dimensions, and a pronunciation evaluation script. Prompts prohibit imitating real people.\n\n"
        "ElevenLabs Voice Design profiles are account-scoped and are not eligible for publication in "
        "ElevenLabs' public Voice Library. Use a separately consented and contract-cleared voice-actor "
        "pipeline for a public shared voice marketplace.\n",
        encoding="utf-8",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("vi", "en", "both"), default="both")
    parser.add_argument("--per-language", type=int, default=1000)
    parser.add_argument("--output", default="dist/voice-design-catalog")
    args = parser.parse_args()
    if not 1 <= args.per_language <= 5000:
        parser.error("--per-language must be between 1 and 5000")
    return args


def main() -> int:
    args = parse_args()
    manifest = write_catalog(Path(args.output), args.language, args.per_language)
    print(
        f"Built {manifest['total_profiles']:,} blueprint profiles "
        f"(VI={manifest['profiles_by_language']['vi']:,}, EN={manifest['profiles_by_language']['en']:,}); "
        "rendered voices=0; paid API calls=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
