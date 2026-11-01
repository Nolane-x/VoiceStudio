#!/usr/bin/env python3
"""Run a bounded, human-reviewed Eleven v4 benchmark over shared voices.

This script makes paid ElevenLabs generation requests only when the explicit
confirmation flag is present. It never retries an ambiguous POST, to avoid
accidental duplicate charges.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

MODEL_ID = "eleven_v4"
ENDPOINT = "https://api.elevenlabs.io/v1/text-to-dialogue"
OUTPUT_FORMAT = "mp3_44100_128"
MAX_REQUEST_CHARACTERS = 1800
MAX_VOICES_PER_LANGUAGE = 4
MAX_TOTAL_REQUESTS = 8
TARGET_RATE = 48_000
TARGET_BITS = 24

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
    return load_module("voice_library_builder_for_eleven_v4", ROOT / "scripts" / "build_voice_library.py")


def load_discovery():
    return load_module(
        "elevenlabs_shared_voice_discovery_for_v4",
        ROOT / "scripts" / "discover_elevenlabs_shared_voices.py",
    )


def request_payload(language: str, voice_id: str) -> dict:
    if language not in SCRIPTS:
        raise ValueError(f"Unsupported language: {language}")
    if not isinstance(voice_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", voice_id):
        raise ValueError("voice_id must be a valid provider voice identifier")
    inputs = [{"text": text, "voice_id": voice_id} for _, text in SCRIPTS[language]]
    character_count = sum(len(item["text"]) for item in inputs)
    if character_count > MAX_REQUEST_CHARACTERS:
        raise ValueError(
            f"Benchmark script is too long for reliable Text-to-Dialogue requests: "
            f"{character_count} > {MAX_REQUEST_CHARACTERS}"
        )
    return {
        "inputs": inputs,
        "model_id": MODEL_ID,
        "language_code": language,
        "apply_text_normalization": "auto",
    }


def generate_dialogue(api_key: str, language: str, voice_id: str, timeout: int = 180) -> bytes:
    if not api_key or not api_key.strip():
        raise RuntimeError("ELEVENLABS_API_KEY is required")
    payload = request_payload(language, voice_id)
    query = urllib.parse.urlencode({"output_format": OUTPUT_FORMAT})
    request = urllib.request.Request(
        f"{ENDPOINT}?{query}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
            "User-Agent": "VoiceStudio-ElevenV4-Benchmark/1.0",
        },
        method="POST",
    )
    # No automatic retry: a timeout after provider-side acceptance could be billable.
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            audio = response.read()
            content_type = str(response.headers.get("Content-Type", "")).lower()
    except urllib.error.HTTPError as exc:
        detail = exc.read(1600).decode("utf-8", errors="replace")
        raise RuntimeError(f"ElevenLabs Eleven v4 returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(
            "ElevenLabs request outcome may be ambiguous; do not retry until usage/history is checked"
        ) from exc
    if "json" in content_type or audio.lstrip().startswith(b"{"):
        detail = audio[:1600].decode("utf-8", errors="replace")
        raise RuntimeError(f"ElevenLabs returned a non-audio response: {detail}")
    if len(audio) < 2048:
        raise RuntimeError(f"ElevenLabs returned an unusably small audio payload ({len(audio)} bytes)")
    return audio


def select_candidates(language: str, offset: int, limit: int, pages: int, api_key: str) -> list[dict]:
    discovery = load_discovery()
    voices, _ = discovery.collect_catalog([language], pages, api_key=api_key)
    # Only query-verified language matches are used. Adoption is a discovery
    # sort, not an assertion that the voice sounds good in this language.
    eligible = [
        voice for voice in voices
        if language in voice.get("languages", [])
        and voice.get("category") in {"high_quality", "professional"}
    ]
    eligible.sort(
        key=lambda voice: (
            -int(voice.get("usage_character_count_1y") or 0),
            -int(voice.get("cloned_by_count") or 0),
            -int(voice.get("usage_character_count_7d") or 0),
            str(voice.get("name", "")).casefold(),
        )
    )
    return eligible[offset:offset + limit]


def make_blind_gallery(rows: list[dict], languages: list[str], built_at: str) -> str:
    cards = []
    for index, row in enumerate(rows, 1):
        cards.append(
            '<article class="sample">'
            f'<p class="meta">BLIND SAMPLE {index:03d} · {row["language"].upper()}</p>'
            f'<h2>Sample {index:03d}</h2>'
            f'<audio controls preload="none" src="{row["audio_file"]}"></audio>'
            f'<div class="script">{row["reference_text_html"]}</div>'
            '<div class="ratings">'
            '<label>Naturalness <input type="number" min="1" max="5" data-field="naturalness"></label>'
            '<label>Pronunciation <input type="number" min="1" max="5" data-field="pronunciation"></label>'
            '<label>Prosody <input type="number" min="1" max="5" data-field="prosody"></label>'
            '<label>Emotional fit <input type="number" min="1" max="5" data-field="emotion"></label>'
            '<label>Accent fit <input type="number" min="1" max="5" data-field="accent_fit"></label>'
            '<label>Overall <input type="number" min="1" max="5" data-field="overall"></label>'
            '</div><label>Listening notes<textarea data-field="notes" rows="2"></textarea></label>'
            '</article>'
        )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Eleven v4 blind voice review</title>
<style>
:root{{color-scheme:light dark;font:15px/1.55 system-ui,sans-serif}}
body{{max-width:1160px;margin:auto;padding:24px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px;margin-top:20px}}
.sample{{border:1px solid #8888;border-radius:14px;padding:16px;min-width:0}}
.meta{{font-size:.78rem;opacity:.7;letter-spacing:.06em}}audio{{width:100%;margin:10px 0}}
.ratings{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}
label{{display:block;font-size:.85rem}}input,textarea{{box-sizing:border-box;width:100%;padding:7px;margin-top:4px;background:transparent;color:inherit;border:1px solid #8888;border-radius:7px}}
button{{padding:8px 12px;border:1px solid #8888;border-radius:8px;background:transparent;color:inherit;cursor:pointer}}
.notice{{border:1px solid #8888;border-radius:10px;padding:12px}}
</style></head><body><header><h1>Eleven v4 · blind marketplace audition</h1>
<p>{len(rows)} anonymized samples · {", ".join(languages)} · built {built_at}</p>
<p class="notice">Voice IDs and provider usage statistics are intentionally withheld in this listening package. Rate naturalness, pronunciation, prosody, emotional fit, accent fit and overall preference before opening the separate analyst manifest.</p>
<p><button id="export">Export listening scores as CSV</button></p></header>
<main class="grid">{''.join(cards)}</main>
<script>
document.getElementById('export').addEventListener('click',()=>{{
 const all=[['blind_sample_id','language','naturalness','pronunciation','prosody','emotion','accent_fit','overall','notes']];
 document.querySelectorAll('.sample').forEach(card=>all.push([
  card.querySelector('.meta').textContent.split(' ')[2],card.querySelector('.meta').textContent.includes('VI')?'vi':'en',
  ...['naturalness','pronunciation','prosody','emotion','accent_fit','overall','notes'].map(n=>card.querySelector('[data-field="'+n+'"]').value)
 ]));
 const csv=all.map(r=>r.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\\n');
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{{type:'text/csv'}}));a.download='eleven-v4-blind-review.csv';a.click();URL.revokeObjectURL(a.href);
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


def run(args) -> int:
    if not args.confirm_paid_api_usage:
        raise RuntimeError("Paid generation blocked: pass --confirm-paid-api-usage explicitly")
    if not 0 <= args.offset <= 100_000:
        raise ValueError("--offset must be between 0 and 100000")
    if not 1 <= args.limit <= MAX_VOICES_PER_LANGUAGE:
        raise ValueError(f"--limit must be between 1 and {MAX_VOICES_PER_LANGUAGE} per language")
    if not 1 <= args.pages_per_query <= 5:
        raise ValueError("--pages-per-query must be between 1 and 5")
    languages = ["vi", "en"] if args.language == "both" else [args.language]
    if len(languages) * args.limit > MAX_TOTAL_REQUESTS:
        raise ValueError(f"At most {MAX_TOTAL_REQUESTS} paid synthesis requests are allowed per run")
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is required")

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    blind_dir = output / "blind-samples"
    blind_dir.mkdir(parents=True, exist_ok=True)
    builder = load_builder()
    successes: list[dict] = []
    failures: list[dict] = []
    selected_count = 0
    sample_counter = 0

    for language in languages:
        selected = select_candidates(language, args.offset, args.limit, args.pages_per_query, api_key)
        print(
            f"[eleven-v4-benchmark] Selected {len(selected)} {language} marketplace voices "
            f"at offset {args.offset}; adoption sort only",
            flush=True,
        )
        selected_count += len(selected)
        for candidate in selected:
            voice_id = candidate["voice_id"]
            sample_counter += 1
            sample_id = f"sample-{sample_counter:03d}"
            masked_id = f"{voice_id[:4]}…{voice_id[-4:]}"
            raw = output / f".{sample_id}.raw.mp3"
            final = blind_dir / f"{sample_id}.wav"
            try:
                audio_bytes = generate_dialogue(api_key, language, voice_id)
                raw.write_bytes(audio_bytes)
                builder.run_ffmpeg_normalize(raw, final, TARGET_RATE, TARGET_BITS)
                watermark = builder.watermark_and_verify(
                    final, TARGET_BITS,
                    context=f"eleven-v4-marketplace.{language}.{voice_id}",
                )
                audio = builder.validate_audio(final, TARGET_RATE, TARGET_BITS, max_duration_s=75.0)
                reference_text = "\n\n".join(text for _, text in SCRIPTS[language])
                successes.append({
                    "blind_sample_id": sample_id,
                    "language": language,
                    "voice_id": voice_id,
                    "voice_name": candidate["name"],
                    "marketplace_category": candidate["category"],
                    "usage_character_count_1y": candidate.get("usage_character_count_1y"),
                    "usage_character_count_7d": candidate.get("usage_character_count_7d"),
                    "cloned_by_count": candidate.get("cloned_by_count"),
                    "discovery_ranks": candidate.get("discovery_ranks", []),
                    "reference_text": reference_text,
                    "audio_file": f"blind-samples/{sample_id}.wav",
                    "audio": audio,
                    "watermark": watermark,
                })
                print(
                    f"[eleven-v4-benchmark] PASS {sample_id} {language} voice={masked_id} "
                    f"duration={audio['duration_seconds']:.2f}s",
                    flush=True,
                )
            except Exception as exc:
                # A failed POST can be ambiguous at the provider. Do not retry automatically.
                failures.append({
                    "blind_sample_id": sample_id,
                    "language": language,
                    "voice_id": voice_id,
                    "voice_name": candidate["name"],
                    "stage": "generate-normalize-watermark-or-validate",
                    "error": f"{type(exc).__name__}: {exc}",
                    "retry_policy": "manual-reconciliation-required; no automatic retry",
                })
                print(f"[eleven-v4-benchmark] FAIL {sample_id} {language} voice={masked_id}: {exc}", flush=True)
                final.unlink(missing_ok=True)
            finally:
                raw.unlink(missing_ok=True)

    # Build a separate blind package. Model IDs, voice IDs and popularity metrics
    # stay in analysis.json and are never included in this ZIP.
    blind_rows = []
    for row in successes:
        import html
        blind_rows.append({
            "language": row["language"],
            "audio_file": row["audio_file"],
            "reference_text_html": "<p>" + "</p><p>".join(
                html.escape(line) for line in row["reference_text"].split("\n\n")
            ) + "</p>",
        })
    built_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    (output / "blind-review.html").write_text(
        make_blind_gallery(blind_rows, languages, built_at), encoding="utf-8",
    )
    (output / "blind-review.csv").write_text(
        "blind_sample_id,language,naturalness,pronunciation,prosody,emotion,accent_fit,overall,notes\n"
        + "".join(f"{row['blind_sample_id']},{row['language']},,,,,,,\n" for row in successes),
        encoding="utf-8",
    )
    (output / "BLIND-REVIEW.md").write_text(
        "# Blind Eleven v4 voice review\n\n"
        "Listen to every WAV and score it before inspecting the separate analysis.json. "
        "This archive deliberately excludes voice names, IDs, marketplace adoption counters and model mapping.\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "benchmark": "ElevenLabs Eleven v4 shared-voice marketplace benchmark",
        "built_at": built_at,
        "model_id": MODEL_ID,
        "endpoint": ENDPOINT,
        "languages": languages,
        "offset": args.offset,
        "limit_per_language": args.limit,
        "selected_voice_count": selected_count,
        "success_count": len(successes),
        "failure_count": len(failures),
        "human_review_required": True,
        "no_automatic_retry": True,
        "metrics_note": "Marketplace usage counters are adoption signals, not quality measures. Audio requires blind human review; automated signal checks and watermark verification do not measure MOS or listener preference.",
        "api_note": "Uses one POST per selected voice with a fixed matched corpus. Combined text is bounded at 1,800 characters per request. No POST retries are made.",
        "marketplace_source": "https://elevenlabs.io/docs/api-reference/voices/voice-library/get-shared",
        "samples": successes,
        "failures": failures,
    }
    (output / "analysis.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    (output / "README.md").write_text(
        "# Eleven v4 shared-voice benchmark\n\n"
        f"- Model: {MODEL_ID}\n- Successful samples: {len(successes)}\n"
        f"- Failures: {len(failures)}\n- Human review required: yes\n\n"
        "Share blind-listening-review.zip with listeners. Keep analysis.json private until scores are submitted. "
        "The script selects marketplace candidates by provider-reported usage signals, not quality scores. "
        "No automatic retry is made after an ambiguous provider POST.\n",
        encoding="utf-8",
    )
    if successes:
        create_blind_archive(output)
    print(
        f"[eleven-v4-benchmark] COMPLETE {len(successes)}/{selected_count} samples; "
        f"{len(failures)} failures; paid requests are limited to selected voices",
        flush=True,
    )
    return 0 if successes and not failures and len(successes) == selected_count else 1


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("vi", "en", "both"), default="both")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=2, help="Maximum voices per language; both is capped at 4")
    parser.add_argument("--pages-per-query", type=int, default=2)
    parser.add_argument("--output", default="dist/elevenlabs-v4-benchmark")
    parser.add_argument("--confirm-paid-api-usage", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(run(parse_args()))
    except Exception as exc:
        print(f"[eleven-v4-benchmark] ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
