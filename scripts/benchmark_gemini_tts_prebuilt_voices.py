#!/usr/bin/env python3
"""Run a bounded, human-reviewed Gemini 3.8 TTS benchmark for prebuilt voices.

Paid generation occurs only with --confirm-paid-api-usage. One POST per
selected voice is attempted, with no retries after ambiguous outcomes.
"""
from __future__ import annotations

import argparse
import base64
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

MODEL_IDS = ("gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
MAX_REQUEST_CHARACTERS = 1800
MAX_VOICES_PER_LANGUAGE = 4
MAX_TOTAL_REQUESTS = 8
TARGET_RATE = 48_000
TARGET_BITS = 24
LONGFORM_MAX_DURATION_S = 75.0
DEFAULT_CATALOG = ROOT / "voice-library" / "gemini-prebuilt-studio-voices.json"

SCRIPTS = {
    "en": [
        ("story", "A quiet decision can change the direction of an entire story. Today, we will follow the small details that reveal why that moment mattered, and what happened next.", "warm, natural storytelling; moderate pace"),
        ("numbers", "At 7:45 in the morning, Linh's research team recorded 3 unusual signals near the northern coast. The result was surprising: the distance was 12.6 kilometres, not 21.6.", "clear instructional delivery; deliberate articulation"),
        ("conversation", "Before we get into the details, here's a question worth keeping in mind: when was the last time a small change made your everyday routine noticeably better?", "natural conversational delivery; relaxed"),
        ("longform", "Imagine arriving in a coastal town just before sunrise. The streets are quiet, the market is beginning to open, and the first boats are returning to shore. Nothing dramatic happens at first. Instead, the story unfolds through ordinary details: a familiar greeting, the sound of waves against the harbour wall, and a shopkeeper preparing the day's first cup of tea. A good narrator needs to make every moment clear without rushing the listener.", "steady audiobook narration; measured pacing"),
    ],
    "vi": [
        ("story", "Đôi khi, một lựa chọn nhỏ có thể thay đổi cả hành trình. Hôm nay, chúng ta sẽ cùng khám phá những chi tiết tưởng như bình thường, nhưng lại quyết định điều gì xảy ra tiếp theo.", "kể chuyện tự nhiên, ấm áp; nhịp vừa phải"),
        ("numbers", "Vào lúc 7 giờ 45 phút sáng, nhóm nghiên cứu của Linh ghi nhận ba tín hiệu bất thường gần bờ biển phía Bắc. Khoảng cách đo được là 12,6 ki-lô-mét, chứ không phải 21,6.", "đọc thông tin rõ ràng; phát âm số cẩn thận"),
        ("conversation", "Trước khi bắt đầu, hãy thử nghĩ về một điều rất quen thuộc: lần gần nhất bạn thay đổi một thói quen nhỏ và nhận ra cuộc sống của mình dễ chịu hơn là khi nào?", "trò chuyện tự nhiên, thân thiện; thư giãn"),
        ("longform", "Hãy tưởng tượng bạn đến một thị trấn ven biển khi mặt trời vừa ló dạng. Những con phố còn yên tĩnh, khu chợ bắt đầu mở cửa, và vài chiếc thuyền đầu tiên trở về sau chuyến ra khơi. Không có sự kiện bất ngờ nào xảy ra. Câu chuyện được tạo nên từ những chi tiết giản dị: một lời chào quen thuộc, tiếng sóng vỗ nhẹ vào bờ kè, và người bán hàng chuẩn bị tách trà đầu tiên trong ngày. Người kể chuyện cần giữ nhịp điệu rõ ràng, tự nhiên, để người nghe muốn ở lại đến cuối cùng.", "thuyết minh dài tự nhiên; nhịp điềm tĩnh, rõ ràng"),
    ],
}


def build_request(model_id: str, voice_id: str, language: str) -> dict:
    if model_id not in MODEL_IDS:
        raise ValueError(f"Unsupported Gemini TTS model: {model_id}")
    if language not in SCRIPTS:
        raise ValueError(f"Unsupported language: {language}")
    if not isinstance(voice_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", voice_id):
        raise ValueError("voice_id must be a valid prebuilt voice identifier")
    content = []
    total_characters = 0
    for _, text, style in SCRIPTS[language]:
        total_characters += len(text)
        content.append({
            "type": "text",
            "text": text,
            "annotations": [{"type": "speech_metadata", "style": style}],
        })
    if total_characters > MAX_REQUEST_CHARACTERS:
        raise ValueError(f"Benchmark corpus is too long: {total_characters} > {MAX_REQUEST_CHARACTERS}")
    return {
        "model": model_id,
        "input": [{"type": "user_input", "content": content}],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voice_id}]},
    }


def extract_audio_bytes(response: dict) -> bytes:
    candidates = []
    direct = response.get("output_audio")
    if isinstance(direct, dict):
        candidates.append(direct.get("data"))
    steps = response.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            blocks = step.get("content")
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "audio":
                    candidates.append(block.get("data"))
    for encoded in reversed(candidates):
        if not isinstance(encoded, str) or not encoded:
            continue
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error):
            continue
        if len(data) >= 2048 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
            return data
    raise RuntimeError("Gemini response did not contain a complete WAV audio block")


def generate_speech(api_key: str, model_id: str, voice_id: str, language: str, timeout: int = 180) -> bytes:
    if not api_key or not api_key.strip():
        raise RuntimeError("GEMINI_API_KEY is required")
    payload = build_request(model_id, voice_id, language)
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "VoiceStudio-Gemini-TTS-Benchmark/1.0",
        },
        method="POST",
    )
    # No retry: a timeout after provider acceptance may already be billable.
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            content_type = str(response.headers.get("Content-Type", "")).lower()
    except urllib.error.HTTPError as exc:
        detail = exc.read(1600).decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini Interactions API returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Gemini request outcome may be ambiguous; do not retry automatically") from exc
    if len(body) > 50 * 1024 * 1024:
        raise RuntimeError("Gemini audio response exceeded the 50 MiB safety limit")
    if "json" not in content_type and not body.lstrip().startswith(b"{"):
        raise RuntimeError(f"Gemini Interactions API returned unexpected content type: {content_type}")
    try:
        response_json = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Gemini Interactions API returned malformed JSON") from exc
    return extract_audio_bytes(response_json)


def load_voice_catalog(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("voices") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Voice catalog must contain a voices array")
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        voice_id = row.get("voice_id") or row.get("id")
        if not isinstance(voice_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", voice_id):
            continue
        voice_type = row.get("type")
        if voice_type is not None and voice_type != "prebuilt":
            continue
        if voice_id in seen:
            continue
        seen.add(voice_id)
        languages = row.get("languages")
        if not isinstance(languages, list):
            single = row.get("language")
            languages = [single] if isinstance(single, str) else []
        result.append({
            "voice_id": voice_id,
            "voice_name": str(row.get("display_name") or row.get("name") or voice_id),
            "archetype": row.get("archetype") or row.get("persona"),
            "languages": sorted({x.lower().split("-", 1)[0] for x in languages if isinstance(x, str)}),
            "source": row.get("source") or data.get("source") or "provider-prebuilt-catalog",
        })
    if not result:
        raise ValueError("Voice catalog contains no eligible prebuilt voices")
    return result


def select_voices(catalog: list[dict], language: str, offset: int, limit: int) -> list[dict]:
    candidates = [
        row for row in catalog
        if not row.get("languages") or language in row["languages"]
    ]
    candidates.sort(key=lambda row: (row["voice_name"].casefold(), row["voice_id"].casefold()))
    return candidates[offset:offset + limit]


def make_blind_gallery(rows: list[dict], model_id: str, built_at: str) -> str:
    cards = []
    for index, row in enumerate(rows, 1):
        cards.append(
            f'<article class="sample" data-sample-id="{html.escape(row["blind_sample_id"], quote=True)}" '
            f'data-language="{html.escape(row["language"], quote=True)}">'
            f'<p class="meta">BLIND SAMPLE {index:03d} · {row["language"].upper()}</p>'
            f'<h2>Sample {index:03d}</h2>'
            f'<audio controls preload="none" src="{html.escape(row["audio_file"], quote=True)}"></audio>'
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
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Gemini TTS blind voice review</title>
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
</style></head><body><header><h1>Gemini 3.8 TTS · blind prebuilt voice audition</h1>
<p>{len(rows)} anonymized samples · model {html.escape(model_id)} · built {html.escape(built_at)}</p>
<p class="notice">Voice names and IDs are hidden until scores are exported and joined to the separate analyst manifest. Rate each sample against the same reference text in its language.</p>
<label>Reviewer code <input id="reviewer-id" maxlength="32" value="reviewer-1"></label>
<p><button id="export">Export listening scores as CSV</button></p></header>
<main class="grid">{''.join(cards)}</main>
<script>
document.getElementById('export').addEventListener('click',()=>{{
 const reviewer=(document.getElementById('reviewer-id').value||'reviewer-1').trim().slice(0,32);
 const all=[['blind_sample_id','language','reviewer_id','naturalness','pronunciation','prosody','emotion','accent_fit','overall','notes']];
 document.querySelectorAll('.sample').forEach(card=>all.push([
  card.dataset.sampleId,card.dataset.language,reviewer,
  ...['naturalness','pronunciation','prosody','emotion','accent_fit','overall','notes'].map(n=>card.querySelector('[data-field="'+n+'"]').value)
 ]));
 const csv=all.map(r=>r.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\\n');
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{{type:'text/csv'}}));a.download='gemini-blind-review.csv';a.click();URL.revokeObjectURL(a.href);
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
    spec = importlib.util.spec_from_file_location("voice_library_builder_for_gemini_benchmark", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load VoiceStudio audio mastering/validation pipeline")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run(args) -> int:
    if not args.confirm_paid_api_usage:
        raise RuntimeError("Paid Gemini generation blocked: pass --confirm-paid-api-usage explicitly")
    if args.model_id not in MODEL_IDS:
        raise ValueError(f"Unsupported model: {args.model_id}")
    if args.language not in {"vi", "en", "both"}:
        raise ValueError(f"Unsupported language selection: {args.language}")
    if not 0 <= args.offset <= 100_000:
        raise ValueError("--offset must be between 0 and 100000")
    if not 1 <= args.limit <= MAX_VOICES_PER_LANGUAGE:
        raise ValueError(f"--limit must be between 1 and {MAX_VOICES_PER_LANGUAGE} per language")
    languages = ["vi", "en"] if args.language == "both" else [args.language]
    if len(languages) * args.limit > MAX_TOTAL_REQUESTS:
        raise ValueError(f"At most {MAX_TOTAL_REQUESTS} paid synthesis requests are allowed per run")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required")

    catalog = load_voice_catalog(Path(args.voice_catalog))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    blind_dir = output / "blind-samples"
    blind_dir.mkdir(parents=True, exist_ok=True)
    builder = load_builder()
    successes: list[dict] = []
    failures: list[dict] = []
    selected_count = 0
    counter = 0

    for language in languages:
        selected = select_voices(catalog, language, args.offset, args.limit)
        selected_count += len(selected)
        if not selected:
            failures.append({
                "language": language,
                "stage": "selection",
                "error": "No eligible prebuilt voices found for this language and offset",
            })
            continue
        for voice in selected:
            counter += 1
            blind_id = f"sample-{counter:03d}"
            raw = output / f".{blind_id}.raw.wav"
            final = blind_dir / f"{blind_id}.wav"
            voice_id = voice["voice_id"]
            try:
                audio_bytes = generate_speech(api_key, args.model_id, voice_id, language)
                raw.write_bytes(audio_bytes)
                builder.run_ffmpeg_normalize(raw, final, TARGET_RATE, TARGET_BITS)
                watermark = builder.watermark_and_verify(
                    final, TARGET_BITS, context=f"gemini-tts.{args.model_id}.{language}.{voice_id}",
                )
                audio = builder.validate_audio(
                    final, TARGET_RATE, TARGET_BITS, max_duration_s=LONGFORM_MAX_DURATION_S,
                )
                reference = "\n\n".join(text for _, text, _ in SCRIPTS[language])
                successes.append({
                    "blind_sample_id": blind_id,
                    "provider": "Google Gemini API",
                    "model_id": args.model_id,
                    "language": language,
                    "voice_id": voice_id,
                    "voice_name": voice["voice_name"],
                    "archetype": voice.get("archetype"),
                    "voice_source": voice.get("source"),
                    "reference_text": reference,
                    "audio_file": f"blind-samples/{blind_id}.wav",
                    "audio": audio,
                    "watermark": watermark,
                })
                print(
                    f"[gemini-tts-benchmark] PASS {blind_id} {language} voice={voice_id} "
                    f"duration={audio['duration_seconds']:.2f}s",
                    flush=True,
                )
            except Exception as exc:
                failures.append({
                    "blind_sample_id": blind_id,
                    "provider": "Google Gemini API",
                    "model_id": args.model_id,
                    "language": language,
                    "voice_id": voice_id,
                    "voice_name": voice["voice_name"],
                    "stage": "generate-normalize-watermark-or-validate",
                    "error": f"{type(exc).__name__}: {exc}",
                    "retry_policy": "manual-reconciliation-required; no automatic retry",
                })
                final.unlink(missing_ok=True)
                print(f"[gemini-tts-benchmark] FAIL {blind_id} {language} {voice_id}: {exc}", flush=True)
            finally:
                raw.unlink(missing_ok=True)

    built_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    blind_rows = []
    for row in successes:
        blind_rows.append({
            "blind_sample_id": row["blind_sample_id"],
            "language": row["language"],
            "audio_file": row["audio_file"],
            "reference_text_html": "<p>" + "</p><p>".join(
                html.escape(part) for part in row["reference_text"].split("\n\n")
            ) + "</p>",
        })
    (output / "blind-review.html").write_text(
        make_blind_gallery(blind_rows, args.model_id, built_at), encoding="utf-8",
    )
    with (output / "blind-review.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["blind_sample_id","language","reviewer_id","naturalness","pronunciation","prosody","emotion","accent_fit","overall","notes"])
        for row in successes:
            writer.writerow([row["blind_sample_id"],row["language"],"reviewer-1","","","","","","",""])
    (output / "BLIND-REVIEW.md").write_text(
        "# Blind Gemini voice review\n\n"
        "Score each sample before inspecting analysis.json. Voice identities and model mapping are kept outside this archive.\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "benchmark": "Gemini 3.8 TTS prebuilt voice benchmark",
        "provider": "Google Gemini API",
        "model_id": args.model_id,
        "endpoint": ENDPOINT,
        "built_at": built_at,
        "languages": languages,
        "offset": args.offset,
        "limit_per_language": args.limit,
        "selected_voice_count": selected_count,
        "success_count": len(successes),
        "failure_count": len(failures),
        "human_review_required": True,
        "no_automatic_retry": True,
        "metrics_note": "Catalog metadata is not audio-quality data. Human listening scores are required for preference ranking; automated checks and watermark verification are not MOS.",
        "api_note": "One POST per selected voice; no automatic retry after ambiguous outcomes. Unary output is provider WAV, normalized by VoiceStudio to 48 kHz/24-bit and watermark verified.",
        "source_catalog": str(Path(args.voice_catalog)),
        "samples": successes,
        "failures": failures,
    }
    (output / "analysis.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "README.md").write_text(
        "# Gemini 3.8 TTS benchmark\n\n"
        f"- Model: {args.model_id}\n- Successful samples: {len(successes)}\n"
        f"- Failed samples: {len(failures)}\n- Human review required: yes\n\n"
        "Merge the blind CSV with the private analysis manifest using the VoiceStudio blind-score merge script. "
        "Provider voice IDs remain managed by Google. No request is retried after a network timeout.\n",
        encoding="utf-8",
    )
    if successes:
        create_blind_archive(output)
    print(
        f"[gemini-tts-benchmark] COMPLETE {len(successes)}/{selected_count} samples; "
        f"{len(failures)} failures; model={args.model_id}",
        flush=True,
    )
    return 0 if successes and not failures and len(successes) == selected_count else 1


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", choices=MODEL_IDS, default="gemini-3.8-flash-tts")
    parser.add_argument("--language", choices=("vi", "en", "both"), default="both")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--voice-catalog", default=str(DEFAULT_CATALOG))
    parser.add_argument("--output", default="dist/gemini-tts-benchmark")
    parser.add_argument("--confirm-paid-api-usage", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(run(parse_args()))
    except Exception as exc:
        print(f"[gemini-tts-benchmark] ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
