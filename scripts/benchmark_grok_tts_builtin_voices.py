#!/usr/bin/env python3
"""Run a bounded, human-reviewed xAI Grok built-in voice audition.

One paid POST is attempted per selected built-in voice. Each voice receives the
same four-part VI or EN corpus, separated by supported long-pause speech tags.
No POST is automatically retried after an ambiguous outcome.
"""
from __future__ import annotations

import argparse
import csv
import html
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

ENDPOINT = "https://api.x.ai/v1/tts"
SUPPORTED_LANGUAGES = ("vi", "en")
MAX_REQUEST_CHARACTERS = 3000
MAX_VOICES_PER_LANGUAGE = 4
MAX_TOTAL_REQUESTS = 8
PRICE_PER_MILLION_CHARACTERS_USD = 15.0
TARGET_RATE = 48_000
TARGET_BITS = 24
MAX_AUDIO_DURATION_S = 120.0
OUTPUT_FORMAT = {
    "codec": "mp3",
    "sample_rate": 24_000,
    "bit_rate": 128_000,
}

SCRIPTS = {
    "en": [
        ("story", "A quiet decision can change the direction of an entire story. Today, we will follow the small details that reveal why that moment mattered, and what happened next."),
        ("numbers", "At 7:45 in the morning, Linh's research team recorded 3 unusual signals near the northern coast. The result was surprising: the distance was 12.6 kilometres, not 21.6."),
        ("conversation", "Before we get into the details, here's a question worth keeping in mind: when was the last time a small change made your everyday routine noticeably better?"),
        ("longform", "Imagine arriving in a coastal town just before sunrise. The streets are quiet, the market is beginning to open, and the first boats are returning to shore. Nothing dramatic happens at first. Instead, the story unfolds through ordinary details: a familiar greeting, the sound of waves against the harbour wall, and a shopkeeper preparing the day's first cup of tea. A good narrator needs to make every moment clear without rushing the listener."),
    ],
    "vi": [
        ("story", "Đôi khi, một lựa chọn nhỏ có thể thay đổi cả hành trình. Hôm nay, chúng ta sẽ cùng khám phá những chi tiết tưởng như bình thường, nhưng lại quyết định điều gì xảy ra tiếp theo."),
        ("numbers", "Vào lúc 7 giờ 45 phút sáng, nhóm nghiên cứu của Linh ghi nhận ba tín hiệu bất thường gần bờ biển phía Bắc. Khoảng cách đo được là 12,6 ki-lô-mét, chứ không phải 21,6."),
        ("conversation", "Trước khi bắt đầu, hãy thử nghĩ về một điều rất quen thuộc: lần gần nhất bạn thay đổi một thói quen nhỏ và nhận ra cuộc sống của mình dễ chịu hơn là khi nào?"),
        ("longform", "Hãy tưởng tượng bạn đến một thị trấn ven biển khi mặt trời vừa ló dạng. Những con phố còn yên tĩnh, khu chợ bắt đầu mở cửa, và vài chiếc thuyền đầu tiên trở về sau chuyến ra khơi. Không có sự kiện bất ngờ nào xảy ra. Câu chuyện được tạo nên từ những chi tiết giản dị: một lời chào quen thuộc, tiếng sóng vỗ nhẹ vào bờ kè, và người bán hàng chuẩn bị tách trà đầu tiên trong ngày. Người kể chuyện cần giữ nhịp điệu rõ ràng, tự nhiên, để người nghe muốn ở lại đến cuối cùng."),
    ],
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load project module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_builder():
    return load_module("voice_library_builder_for_grok_tts", ROOT / "scripts" / "build_voice_library.py")


def load_discovery():
    return load_module("grok_builtin_voice_discovery_for_benchmark", ROOT / "scripts" / "discover_grok_builtin_voices.py")


def combined_text(language: str) -> str:
    if language not in SCRIPTS:
        raise ValueError(f"Unsupported language: {language}")
    return "\n\n[long-pause]\n\n".join(text for _, text in SCRIPTS[language])


def build_request(voice_id: str, language: str) -> dict:
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    if not isinstance(voice_id, str) or not re.fullmatch(r"[a-z0-9_-]{1,64}", voice_id):
        raise ValueError("voice_id must be a valid provider built-in voice identifier")
    text = combined_text(language)
    if len(text) > MAX_REQUEST_CHARACTERS:
        raise ValueError(
            f"Matched four-part corpus exceeds VoiceStudio's budget limit: "
            f"{len(text)} > {MAX_REQUEST_CHARACTERS} characters"
        )
    return {
        "text": text,
        "voice_id": voice_id,
        "language": language,
        "output_format": dict(OUTPUT_FORMAT),
        "text_normalization": True,
    }


def estimate_max_cost_usd(language_count: int, limit_per_language: int, max_chars: int = MAX_REQUEST_CHARACTERS) -> float:
    if language_count not in {1, 2}:
        raise ValueError("language_count must be one or two")
    if not 1 <= limit_per_language <= MAX_VOICES_PER_LANGUAGE:
        raise ValueError("limit_per_language is outside the permitted range")
    requests = language_count * limit_per_language
    if requests > MAX_TOTAL_REQUESTS:
        raise ValueError(f"At most {MAX_TOTAL_REQUESTS} paid TTS requests are allowed")
    return round(requests * max_chars * PRICE_PER_MILLION_CHARACTERS_USD / 1_000_000, 6)


def generate_speech(api_key: str, voice_id: str, language: str, timeout: int = 180) -> bytes:
    if not api_key or not api_key.strip():
        raise RuntimeError("XAI_API_KEY is required")
    payload = build_request(voice_id, language)
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
            "User-Agent": "VoiceStudio-Grok-TTS-Benchmark/1.0",
        },
        method="POST",
    )
    # Never automatically retry POST: a timeout can occur after provider-side
    # acceptance and billing. Reconcile the xAI usage dashboard before retrying.
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            audio = response.read()
            content_type = str(response.headers.get("Content-Type", "")).lower()
    except urllib.error.HTTPError as exc:
        detail = exc.read(1600).decode("utf-8", errors="replace")
        raise RuntimeError(f"xAI TTS returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(
            "xAI TTS request outcome may be ambiguous; do not retry until usage/history is reconciled"
        ) from exc
    if len(audio) < 2048:
        raise RuntimeError(f"xAI TTS returned an unusably small audio payload ({len(audio)} bytes)")
    if "json" in content_type or audio.lstrip().startswith(b"{"):
        detail = audio[:1600].decode("utf-8", errors="replace")
        raise RuntimeError(f"xAI TTS returned a non-audio response: {detail}")
    return audio


def load_voice_catalog(path: Path) -> list[dict]:
    discovery = load_discovery()
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("voices") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Grok voice catalogue must contain a voices array")
    result = []
    seen = set()
    for raw in rows:
        voice = discovery.normalize_voice(raw)
        if voice is None or voice["kind"] != "provider_managed_builtin":
            continue
        if voice["voice_id"] in seen:
            continue
        seen.add(voice["voice_id"])
        result.append(voice)
    return result


def select_voices(catalog: list[dict], language: str, offset: int, limit: int) -> list[dict]:
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    if offset < 0 or limit < 1 or limit > MAX_VOICES_PER_LANGUAGE:
        raise ValueError("Invalid voice offset or limit")
    eligible = [
        voice for voice in catalog
        if language in voice.get("language_scope", [])
        and voice.get("kind") == "provider_managed_builtin"
    ]
    eligible.sort(key=lambda voice: voice["voice_id"])
    return eligible[offset:offset + limit]


def make_blind_gallery(rows: list[dict], languages: list[str], built_at: str) -> str:
    cards = []
    for index, row in enumerate(rows, 1):
        parts = [
            f"<h3>{html.escape(title)}</h3><p>{html.escape(text)}</p>"
            for title, text in SCRIPTS[row["language"]]
        ]
        cards.append(
            f'<article class="sample" data-sample-id="{html.escape(row["blind_sample_id"], quote=True)}" '
            f'data-language="{html.escape(row["language"], quote=True)}" '
            f'data-scenario="mixed-four-part-corpus">'
            f'<p class="meta">BLIND SAMPLE {index:03d} · {row["language"].upper()}</p>'
            f'<h2>Sample {index:03d}</h2>'
            f'<audio controls preload="none" src="{html.escape(row["audio_file"], quote=True)}"></audio>'
            f'<div class="script">{"".join(parts)}</div>'
            '<div class="ratings">'
            '<label>Naturalness <input type="number" min="1" max="5" data-field="naturalness"></label>'
            '<label>Pronunciation <input type="number" min="1" max="5" data-field="pronunciation"></label>'
            '<label>Prosody <input type="number" min="1" max="5" data-field="prosody"></label>'
            '<label>Emotion <input type="number" min="1" max="5" data-field="emotion"></label>'
            '</div><label>Listening notes<textarea data-field="notes" rows="2"></textarea></label>'
            '</article>'
        )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Grok blind voice review</title>
<style>
:root{{color-scheme:light dark;font:15px/1.55 system-ui,sans-serif}}body{{max-width:1160px;margin:auto;padding:24px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px;margin-top:20px}}
.sample{{border:1px solid #8888;border-radius:14px;padding:16px;min-width:0}}
.meta{{font-size:.78rem;opacity:.7;letter-spacing:.06em}}audio{{width:100%;margin:10px 0}}
.ratings{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}
label{{display:block;font-size:.85rem}}input,textarea{{box-sizing:border-box;width:100%;padding:7px;margin-top:4px;background:transparent;color:inherit;border:1px solid #8888;border-radius:7px}}
button{{padding:8px 12px;border:1px solid #8888;border-radius:8px;background:transparent;color:inherit;cursor:pointer}}
.notice{{border:1px solid #8888;border-radius:10px;padding:12px}}.script h3{{margin-bottom:4px}}.script p{{margin-top:4px}}
</style></head><body><header><h1>Grok TTS · blind built-in voice review</h1>
<p>{len(rows)} anonymized samples · {html.escape(", ".join(languages))} · built {html.escape(built_at)}</p>
<p class="notice">Each sample contains the same four-part matched corpus: story, numbers, conversation and long-form narration. Voice names and IDs are hidden. Rate the whole composite voice output; the four sections are not individually separated into independent scores.</p>
<label>Reviewer code <input id="reviewer-id" maxlength="32" value="reviewer-1"></label>
<p><button id="export">Export listening scores as CSV</button></p></header>
<main class="grid">{''.join(cards)}</main>
<script>
document.getElementById('export').addEventListener('click',()=>{{
 const reviewer=(document.getElementById('reviewer-id').value||'reviewer-1').trim().slice(0,32);
 const all=[['blind_sample_id','language','scenario','reviewer_id','naturalness','pronunciation','prosody','emotion','notes']];
 document.querySelectorAll('.sample').forEach(card=>all.push([
  card.dataset.sampleId,card.dataset.language,card.dataset.scenario,reviewer,
  ...['naturalness','pronunciation','prosody','emotion','notes'].map(n=>card.querySelector('[data-field="'+n+'"]').value)
 ]));
 const csv=all.map(row=>row.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\\n');
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{{type:'text/csv'}}));a.download='grok-blind-review.csv';a.click();URL.revokeObjectURL(a.href);
}});
</script></body></html>"""


def create_blind_archive(output: Path) -> Path:
    archive = output / "blind-listening-review.zip"
    files = [output / "blind-review.html", output / "blind-review.csv", output / "BLIND-REVIEW.md"]
    files.extend(sorted((output / "blind-samples").glob("*.wav")))
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4) as bundle:
        for path in files:
            if not path.is_file():
                raise FileNotFoundError(f"Blind review package input is missing: {path}")
            bundle.write(path, path.relative_to(output).as_posix())
    return archive


def load_builder():
    path = ROOT / "scripts" / "build_voice_library.py"
    spec = importlib.util.spec_from_file_location("voice_library_builder_for_grok_benchmark", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load the audio builder at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run(args) -> int:
    if not args.confirm_paid_api_usage:
        raise RuntimeError("Paid xAI TTS generation blocked: pass --confirm-paid-api-usage explicitly")
    if args.language not in {"both", "vi", "en"}:
        raise ValueError("--language must be both, vi or en")
    if not 0 <= args.offset <= 100_000:
        raise ValueError("--offset must be between 0 and 100000")
    if not 1 <= args.limit <= MAX_VOICES_PER_LANGUAGE:
        raise ValueError(f"--limit must be between 1 and {MAX_VOICES_PER_LANGUAGE} per language")
    languages = ["vi", "en"] if args.language == "both" else [args.language]
    if len(languages) * args.limit > MAX_TOTAL_REQUESTS:
        raise ValueError(f"At most {MAX_TOTAL_REQUESTS} paid synthesis requests are allowed per run")
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        raise RuntimeError("XAI_API_KEY is required")

    catalog = load_voice_catalog(Path(args.voice_catalog))
    selected_by_language = {
        language: select_voices(catalog, language, args.offset, args.limit)
        for language in languages
    }
    selected_count = sum(len(rows) for rows in selected_by_language.values())
    if selected_count < 1:
        raise RuntimeError("No eligible built-in voices found for the selected language/offset")
    total_characters = sum(
        len(combined_text(language)) * len(rows)
        for language, rows in selected_by_language.items()
    )
    estimated_cost = round(total_characters * PRICE_PER_MILLION_CHARACTERS_USD / 1_000_000, 6)
    budget_ceiling = round(
        selected_count * MAX_REQUEST_CHARACTERS * PRICE_PER_MILLION_CHARACTERS_USD / 1_000_000, 6,
    )
    print(
        f"[grok-tts-benchmark] Estimated text charge USD {estimated_cost:.6f}; "
        f"hard corpus-length ceiling USD {budget_ceiling:.6f}; "
        f"{selected_count} POST request(s), {total_characters} input characters",
        flush=True,
    )

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    blind_dir = output / "blind-samples"
    blind_dir.mkdir(parents=True, exist_ok=True)
    builder = load_builder()
    successes: list[dict] = []
    failures: list[dict] = []
    sample_counter = 0

    for language in languages:
        selected = selected_by_language[language]
        print(
            f"[grok-tts-benchmark] Selected {len(selected)} {language} built-in voices "
            f"at offset {args.offset}; provider menu order is not a popularity score",
            flush=True,
        )
        for voice in selected:
            sample_counter += 1
            sample_id = f"sample-{sample_counter:03d}"
            voice_id = voice["voice_id"]
            raw = output / f".{sample_id}.raw.mp3"
            final = blind_dir / f"{sample_id}.wav"
            try:
                audio_bytes = generate_speech(api_key, voice_id, language)
                raw.write_bytes(audio_bytes)
                builder.run_ffmpeg_normalize(raw, final, TARGET_RATE, TARGET_BITS)
                watermark = builder.watermark_and_verify(
                    final, TARGET_BITS, context=f"grok-tts-builtin.{language}.{voice_id}",
                )
                audio = builder.validate_audio(
                    final, TARGET_RATE, TARGET_BITS, max_duration_s=MAX_AUDIO_DURATION_S,
                )
                reference = combined_text(language)
                successes.append({
                    "blind_sample_id": sample_id,
                    "provider": "xAI",
                    "engine": "grok-tts",
                    "engine_label": "Grok TTS",
                    "model_id": "xAI TTS API",
                    "language": language,
                    "voice_id": voice_id,
                    "voice_label": voice["name"],
                    "voice_profile": {
                        "tone": voice.get("tone"),
                        "use_cases": voice.get("use_cases", []),
                    },
                    "scenario_id": "mixed-four-part-corpus",
                    "scenario_title": "Story, numbers, conversation and long-form",
                    "reference_text": reference,
                    "rights": {
                        "status": "provider-managed-built-in",
                        "commercial_use": "subject-to-xai-account-plan-and-current-provider-terms",
                    },
                    "audio_file": f"blind-samples/{sample_id}.wav",
                    "audio": audio,
                    "watermark": watermark,
                })
                print(
                    f"[grok-tts-benchmark] PASS {sample_id} {language} "
                    f"duration={audio['duration_seconds']:.2f}s",
                    flush=True,
                )
            except Exception as exc:
                failures.append({
                    "blind_sample_id": sample_id,
                    "provider": "xAI",
                    "language": language,
                    "voice_id": voice_id,
                    "voice_name": voice["name"],
                    "stage": "generate-normalize-watermark-or-validate",
                    "error": f"{type(exc).__name__}: {exc}",
                    "retry_policy": "manual-reconciliation-required; no automatic retry",
                })
                final.unlink(missing_ok=True)
                print(
                    f"[grok-tts-benchmark] FAIL {sample_id} {language} voice={voice_id}: {exc}",
                    flush=True,
                )
            finally:
                raw.unlink(missing_ok=True)

    built_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    blind_rows = [
        {
            "blind_sample_id": row["blind_sample_id"],
            "language": row["language"],
            "audio_file": row["audio_file"],
        }
        for row in successes
    ]
    (output / "blind-review.html").write_text(
        make_blind_gallery(blind_rows, languages, built_at), encoding="utf-8",
    )
    with (output / "blind-review.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "blind_sample_id", "language", "scenario", "reviewer_id",
            "naturalness", "pronunciation", "prosody", "emotion", "notes",
        ])
        for row in successes:
            writer.writerow([
                row["blind_sample_id"], row["language"], "mixed-four-part-corpus",
                "reviewer-1", "", "", "", "", "",
            ])
    (output / "BLIND-REVIEW.md").write_text(
        "# Grok TTS blind voice review\n\n"
        "Each WAV is one provider built-in voice reading the same four-part corpus for its language. "
        "Listen and rate the overall composite output. This is not a set of four separately scored files. "
        "The archive omits voice IDs, names and profile metadata; keep analysis.json private until review closes.\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "benchmark": "xAI Grok built-in voice matched corpus",
        "built_at": built_at,
        "endpoint": ENDPOINT,
        "languages": languages,
        "selected_voice_count": selected_count,
        "successful_samples": len(successes),
        "failure_count": len(failures),
        "matched_scenarios": ["story", "numbers", "conversation", "longform"],
        "scenario_scoring_note": "All four script sections are combined into one request and one WAV per voice to limit paid requests. Human ratings apply to the composite; this run does not create per-scenario separate scores.",
        "estimated_input_characters": total_characters,
        "estimated_text_charge_usd": estimated_cost,
        "hard_request_character_limit": MAX_REQUEST_CHARACTERS,
        "hard_max_cost_usd_at_documented_rate": budget_ceiling,
        "price_source": "https://docs.x.ai/developers/model-capabilities/audio/voice",
        "human_review_required": True,
        "no_automatic_post_retries": True,
        "quality_note": "Human blind ratings are cohort preference, not standardized MOS. API support for vi/en does not guarantee equal native pronunciation for every voice.",
        "rights_note": "Provider voice IDs remain controlled by xAI. Commercial use is subject to account plan and current provider terms; this benchmark does not grant redistribution rights.",
        "samples": successes,
        "failures": failures,
    }
    (output / "analysis.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    (output / "README.md").write_text(
        "# Grok built-in TTS benchmark\n\n"
        f"- Successful samples: {len(successes)}/{selected_count}\n"
        f"- Failed samples: {len(failures)}\n"
        f"- Estimated text charge: USD {estimated_cost:.6f}\n"
        f"- Hard budget ceiling from request character cap: USD {budget_ceiling:.6f}\n"
        "- Human review required: yes\n\n"
        "Share blind-listening-review.zip with listeners. Keep analysis.json private until review is complete. "
        "Each voice reads the same four-part composite corpus in its language. The exported rating is for the composite sample, not separate per-scenario audio.\n",
        encoding="utf-8",
    )
    if successes:
        create_blind_archive(output)
    print(
        f"[grok-tts-benchmark] COMPLETE {len(successes)}/{selected_count} samples; "
        f"{len(failures)} failures; estimated text charge USD {estimated_cost:.6f}",
        flush=True,
    )
    return 0 if successes and not failures and len(successes) == selected_count else 1


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("vi", "en", "both"), default="both")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=2, help="Maximum voices per language; both is capped at eight total requests")
    parser.add_argument("--voice-catalog", type=Path, default=Path("dist/grok-builtin-voices/catalog.json"))
    parser.add_argument("--output", default="dist/grok-tts-benchmark")
    parser.add_argument("--confirm-paid-api-usage", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(run(parse_args()))
    except Exception as exc:
        print(f"[grok-tts-benchmark] ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
