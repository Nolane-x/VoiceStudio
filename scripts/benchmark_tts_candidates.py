#!/usr/bin/env python3
"""Run matched TTS candidate evaluations on GitHub Actions CPU runners."""
from __future__ import annotations

import argparse
import csv
import html
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

SCRIPTS = {
    "en": [
        ("story", "Narrative prose",
         "A quiet decision can change the direction of an entire story. Today, we will follow the small details that reveal why that moment mattered, and what happened next."),
        ("numbers", "Numbers, names and punctuation",
         "At 7:45 in the morning, Linh's research team recorded 3 unusual signals near the northern coast. The result was surprising: the distance was 12.6 kilometres, not 21.6."),
    ],
    "vi": [
        ("story", "Văn kể chuyện",
         "Đôi khi, một lựa chọn nhỏ có thể thay đổi cả hành trình. Hôm nay, chúng ta sẽ cùng khám phá những chi tiết tưởng như bình thường, nhưng lại quyết định điều gì xảy ra tiếp theo."),
        ("numbers", "Số, tên riêng và dấu câu",
         "Vào lúc 7 giờ 45 phút sáng, nhóm nghiên cứu của Linh ghi nhận ba tín hiệu bất thường gần bờ biển phía Bắc. Khoảng cách đo được là 12,6 ki-lô-mét, chứ không phải 21,6."),
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
    return load_module("voice_library_builder_for_benchmark", ROOT / "scripts" / "build_voice_library.py")


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value).casefold()
    output = []
    for char in value:
        category = unicodedata.category(char)
        output.append(char if category[0] in {"L", "N"} or char.isspace() else " ")
    return re.sub(r"\s+", " ", "".join(output)).strip()


def edit_distance(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for i, token in enumerate(left, 1):
        current = [i]
        for j, other in enumerate(right, 1):
            current.append(min(
                previous[j - 1] + (token != other),
                current[j - 1] + 1,
                previous[j] + 1,
            ))
        previous = current
    return previous[-1]


def error_metrics(reference: str, hypothesis: str, language: str) -> dict:
    ref, hyp = normalize_text(reference), normalize_text(hypothesis)
    ref_tokens, hyp_tokens = ref.split(), hyp.split()
    return {
        "token_error_rate": round(edit_distance(ref_tokens, hyp_tokens) / max(1, len(ref_tokens)), 4),
        "token_unit": "words" if language == "en" else "whitespace-delimited Vietnamese syllables",
        "character_error_rate": round(edit_distance(list(ref), list(hyp)) / max(1, len(ref)), 4),
        "reference_token_count": len(ref_tokens),
        "hypothesis_token_count": len(hyp_tokens),
    }


def safe_slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return (re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()[:72] or "sample")


def make_candidates(builder, languages: list[str], failures: list[dict]) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    revisions: dict = {}

    # Supertonic is a comparison-only candidate. Reuse the exact immutable
    # revision already pinned by the VoiceStudio application.
    try:
        constants = load_module(
            "supertonic3_constants_for_benchmark",
            BACKEND / "engines" / "supertonic3" / "constants.py",
        )
        from huggingface_hub import snapshot_download
        from supertonic import TTS

        revision = constants.PINNED_REVISION_SHA
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise RuntimeError("Invalid VoiceStudio Supertonic revision pin")
        model_dir = snapshot_download(repo_id="Supertone/supertonic-3", revision=revision)
        tts = TTS(model="supertonic-3", model_dir=model_dir, auto_download=False)
        revisions["supertonic"] = {"repo": "Supertone/supertonic-3", "revision": revision, "license": "OpenRAIL-M"}
        for language in languages:
            for voice_id in ("M1", "F3"):
                style = tts.get_voice_style(voice_name=voice_id)

                def render(text: str, path: Path, *, _tts=tts, _style=style, _lang=language):
                    import numpy as np
                    import soundfile as sf

                    waveform, _ = _tts.synthesize(
                        text=text, voice_style=_style, total_steps=10,
                        speed=1.0, max_chunk_length=300, silence_duration=0.22, lang=_lang,
                    )
                    audio = np.asarray(waveform, dtype=np.float32).squeeze()
                    if audio.ndim != 1 or not audio.size or not np.isfinite(audio).all():
                        raise RuntimeError(f"Invalid Supertonic waveform: {audio.shape}")
                    sf.write(str(path), audio, 44100, subtype="FLOAT", format="WAV")

                rows.append({
                    "engine": "supertonic", "engine_label": "Supertonic 3",
                    "voice_id": voice_id, "language": language, "render": render,
                    "rights": {"status": "manual-review-required", "commercial_use": "not-cleared-by-this-benchmark",
                               "notice": "OpenRAIL-M model terms apply. This benchmark does not grant commercial-use clearance."},
                })
    except Exception as exc:
        failures.append({"engine": "supertonic", "stage": "load", "error": f"{type(exc).__name__}: {exc}"})

    # VieNeu provides the main Vietnamese comparison plus bilingual English.
    try:
        tts, presets, revision = builder.prepare_vieneu()
        revisions["vieneu"] = revision
        selected = []
        preferred = next((p for p in presets if "adam_bua" in str(p[1]).casefold()), None)
        if preferred:
            selected.append(preferred)
        selected.extend(p for p in presets if p[1] not in {x[1] for x in selected})
        if len(selected) < 2:
            raise RuntimeError("Need two distinct VieNeu preset identities")
        for language in languages:
            for label, voice_id in selected[:2]:
                def render(text: str, path: Path, *, _voice=voice_id):
                    builder.render_vieneu_wav(tts, _voice, text, path)

                rows.append({
                    "engine": "vieneu", "engine_label": "VieNeu-TTS v3 Turbo",
                    "voice_id": str(voice_id), "voice_label": str(label),
                    "language": language, "render": render,
                    "rights": {"status": "upstream-preset-consent-stated",
                               "commercial_use": "upstream-model-card-permits-generated-audio",
                               "notice": "Keep source attribution and review the upstream model card."},
                })
    except Exception as exc:
        failures.append({"engine": "vieneu", "stage": "load", "error": f"{type(exc).__name__}: {exc}"})

    # Kokoro is English-only and included only as a matched English candidate.
    if "en" in languages:
        try:
            prepared, voices, revision = builder.prepare_kokoro()
            revisions["kokoro"] = revision
            for voice_id in ("af_heart", "af_bella"):
                voice = next((v for v in voices if v["id"] == voice_id), None)
                if voice is None:
                    continue

                def render(text: str, path: Path, *, _voice=voice_id):
                    builder.render_kokoro_wav(prepared, _voice, text, path)

                rows.append({
                    "engine": "kokoro", "engine_label": "Kokoro-82M",
                    "voice_id": f"en-kokoro-v1-{voice_id}", "voice_label": voice["display_name"],
                    "quality_grade": voice["quality_grade"], "language": "en", "render": render,
                    "rights": {"status": "upstream-apache-2.0-model-voice-assets",
                               "commercial_use": "apache-2.0-model-and-voice-assets",
                               "notice": "Apache-2.0 applies to model and bundled voice assets, not identity or endorsement rights."},
                })
        except Exception as exc:
            failures.append({"engine": "kokoro", "stage": "load", "error": f"{type(exc).__name__}: {exc}"})

    # Piper is retained as an English-only legacy baseline, not a recommended
    # commercially cleared voice source.
    if "en" in languages:
        try:
            voice, info = builder.prepare_piper()
            revisions["piper"] = info["revision"]
            for label, speaker_id in info["speaker_pairs"][:2]:
                def render(text: str, path: Path, *, _id=speaker_id):
                    builder.render_piper_wav(voice, _id, path)

                rows.append({
                    "engine": "piper", "engine_label": "Piper LibriTTS High",
                    "voice_id": f"en-piper-libritts-high-{speaker_id:04d}",
                    "voice_label": str(label), "language": "en", "render": render,
                    "rights": {"status": "restricted-evidence",
                               "commercial_use": "not-cleared-by-this-build",
                               "notice": "Piper/LibriTTS source records do not establish blanket commercial or publicity rights."},
                })
        except Exception as exc:
            failures.append({"engine": "piper", "stage": "load", "error": f"{type(exc).__name__}: {exc}"})

    if not rows:
        raise RuntimeError("No TTS candidate initialized")
    return rows, revisions


def transcribe(path: Path, language: str, model_name: str, state: dict) -> dict:
    try:
        if "model" not in state:
            from faster_whisper import WhisperModel
            state["model"] = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=4)
        segments, info = state["model"].transcribe(
            str(path), language=language, beam_size=3, vad_filter=False,
            condition_on_previous_text=False,
        )
        return {
            "status": "completed",
            "model": f"faster-whisper {model_name} CPU int8",
            "detected_language": getattr(info, "language", None),
            "language_probability": round(float(getattr(info, "language_probability", 0.0)), 4),
            "transcript": " ".join(str(s.text).strip() for s in segments).strip(),
        }
    except Exception as exc:
        return {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}", "transcript": ""}


def make_gallery(rows: list[dict], manifest: dict) -> str:
    cards = []
    for row in rows:
        m = row.get("asr_metrics", {})
        token_name = "WER" if row["language"] == "en" else "Vietnamese syllable error"
        cards.append(f"""
<article class="sample">
<div class="meta">{html.escape(row['language'].upper())} · {html.escape(row['engine'])}</div>
<h2>{html.escape(row.get('voice_label', row['voice_id']))}</h2>
<p>{html.escape(row['scenario_title'])}</p>
<audio controls preload="none" src="{html.escape(row['audio_file'], quote=True)}"></audio>
<p><b>Reference</b><br>{html.escape(row['reference_text'])}</p>
<p><b>ASR</b><br>{html.escape(row.get('asr', {}).get('transcript', ''))}</p>
<div class="metrics"><span>{token_name}: {m.get('token_error_rate', 'n/a')}</span>
<span>CER: {m.get('character_error_rate', 'n/a')}</span><span>RTFx: {row['rtfx']:.2f}</span></div>
<div class="ratings">
<label>Naturalness <input type="number" min="1" max="5" data-field="naturalness"></label>
<label>Pronunciation <input type="number" min="1" max="5" data-field="pronunciation"></label>
<label>Prosody <input type="number" min="1" max="5" data-field="prosody"></label>
<label>Emotion <input type="number" min="1" max="5" data-field="emotion"></label>
</div><label>Notes<textarea data-field="notes" rows="2"></textarea></label>
</article>""")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>VoiceStudio TTS Benchmark</title>
<style>
:root{{color-scheme:light dark;font:15px/1.55 system-ui,sans-serif}}body{{max-width:1160px;margin:auto;padding:28px 20px}}
header{{border-bottom:1px solid #8886;padding-bottom:18px}}.notice{{border:1px solid #8888;border-radius:12px;padding:12px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px;margin-top:20px}}
.sample{{border:1px solid #8888;border-radius:14px;padding:16px;min-width:0}}.meta{{font-size:.75rem;opacity:.7;letter-spacing:.08em}}
audio{{width:100%;margin:10px 0}}.metrics{{display:flex;flex-wrap:wrap;gap:8px}}.metrics span{{border:1px solid #8888;border-radius:20px;padding:3px 9px;font-size:.8rem}}
.ratings{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}label{{display:block;font-size:.85rem}}
input,textarea{{box-sizing:border-box;width:100%;padding:7px;margin-top:4px;background:transparent;color:inherit;border:1px solid #8888;border-radius:7px}}
</style></head><body><header><div>VoiceStudio · GitHub Actions benchmark</div>
<h1>Listen before choosing a voice</h1><p>Built {html.escape(manifest['built_at'])} · {len(rows)} samples</p>
<div class="notice"><b>Important:</b> RTFx and ASR error are diagnostics, not measures of human naturalness. Listen for Vietnamese tones, names, pacing, emotion and sentence endings. Supertonic OpenRAIL-M and Piper samples are not automatically commercially cleared.</div>
<p><button id="export">Export human ratings CSV</button></p></header><div class="grid">{''.join(cards)}</div>
<script>
document.getElementById('export').addEventListener('click',()=>{{
 const all=[['language','engine_voice','scenario','naturalness','pronunciation','prosody','emotion','notes']];
 document.querySelectorAll('.sample').forEach(c=>all.push([
 c.querySelector('.meta').textContent,c.querySelector('h2').textContent,c.querySelector('p').textContent,
 ...['naturalness','pronunciation','prosody','emotion','notes'].map(n=>c.querySelector('[data-field="'+n+'"]').value)]));
 const csv=all.map(r=>r.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\n');
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{{type:'text/csv'}}));a.download='human-review.csv';a.click();URL.revokeObjectURL(a.href);
}});
</script></body></html>"""


def run(args) -> int:
    import soundfile as sf

    builder = load_builder()
    languages = ["en", "vi"] if args.language == "both" else [args.language]
    output = Path(args.output).resolve()
    sample_dir = output / "samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    failures: list[dict] = []
    candidates, revisions = make_candidates(builder, languages, failures)

    # Warm each candidate once before timing to avoid charging model/session
    # initialization to one voice and not the next.
    for candidate in candidates:
        warm = output / ".warmup.wav"
        try:
            candidate["render"](
                "This is a short voice benchmark warm-up." if candidate["language"] == "en"
                else "Đây là câu thử giọng ngắn.",
                warm,
            )
        except Exception as exc:
            failures.append({"engine": candidate["engine"], "voice_id": candidate["voice_id"],
                             "stage": "warmup", "error": f"{type(exc).__name__}: {exc}"})
        finally:
            warm.unlink(missing_ok=True)

    asr_state: dict = {}
    results: list[dict] = []
    expected = sum(len(TEXTS[c["language"]]) for c in candidates)
    for index, candidate in enumerate(candidates, 1):
        for scenario_id, scenario_title, reference in TEXTS[candidate["language"]]:
            slug = safe_slug(f"{index}-{candidate['engine']}-{candidate['voice_id']}-{candidate['language']}-{scenario_id}")
            raw = output / f".{slug}.raw.wav"
            final = sample_dir / f"{slug}.wav"
            try:
                start = time.perf_counter()
                candidate["render"](reference, raw)
                infer_seconds = max(0.000001, time.perf_counter() - start)
                if not raw.is_file() or raw.stat().st_size < 2048:
                    raise RuntimeError("TTS returned no usable WAV")
                builder.run_ffmpeg_normalize(raw, final, TARGET_RATE, TARGET_BITS)
                watermark = builder.watermark_and_verify(
                    final, TARGET_BITS,
                    context=f"tts-benchmark.{candidate['engine']}.{candidate['voice_id']}.{candidate['language']}.{scenario_id}",
                )
                audio = builder.validate_audio(final, TARGET_RATE, TARGET_BITS)
                asr = transcribe(final, candidate["language"], args.asr_model, asr_state)
                metrics = (
                    error_metrics(reference, asr["transcript"], candidate["language"])
                    if asr["status"] == "completed" else {}
                )
                duration = float(audio["duration_seconds"])
                results.append({
                    "engine": candidate["engine"], "engine_label": candidate["engine_label"],
                    "voice_id": candidate["voice_id"], "voice_label": candidate.get("voice_label", candidate["voice_id"]),
                    "quality_grade": candidate.get("quality_grade"), "language": candidate["language"],
                    "scenario_id": scenario_id, "scenario_title": scenario_title,
                    "reference_text": reference, "audio_file": f"samples/{final.name}",
                    "audio_duration_seconds": duration, "inference_seconds": round(infer_seconds, 4),
                    "rtfx": round(duration / infer_seconds, 4),
                    "characters_per_second": round(len(reference) / infer_seconds, 2),
                    "audio": audio, "watermark": watermark, "asr": asr,
                    "asr_metrics": metrics, "rights": candidate["rights"],
                })
                print(f"[tts-benchmark] PASS {slug} RTFx={duration / infer_seconds:.2f}", flush=True)
            except Exception as exc:
                failures.append({"engine": candidate["engine"], "voice_id": candidate["voice_id"],
                                 "language": candidate["language"], "scenario": scenario_id,
                                 "stage": "render-or-verify", "error": f"{type(exc).__name__}: {exc}"})
                print(f"[tts-benchmark] FAIL {slug}: {type(exc).__name__}: {exc}", flush=True)
                final.unlink(missing_ok=True)
            finally:
                raw.unlink(missing_ok=True)

    manifest = {
        "schema_version": 1, "benchmark": "VoiceStudio TTS candidate benchmark",
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_commit": os.environ.get("GITHUB_SHA"), "languages": languages,
        "output_format": "mono 48 kHz PCM-24", "asr_model": args.asr_model,
        "model_revisions": revisions, "sample_count": len(results),
        "expected_sample_count": expected, "failure_count": len(failures),
        "human_review_required": True,
        "metrics_note": "RTFx is audio duration divided by warm synthesis wall time. English token error is WER; Vietnamese token error counts whitespace-delimited syllables, not lexical words. CER is character error. None is MOS or human preference.",
        "samples": results, "failures": failures,
    }
    (output / "benchmark.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "index.html").write_text(make_gallery(results, manifest), encoding="utf-8")
    (output / "README.md").write_text(
        "# VoiceStudio TTS candidate benchmark\n\n"
        "Open index.html and listen to matched voice samples. The page exports human listening ratings as CSV.\n\n"
        "RTFx measures speed; ASR token/CER errors are intelligibility diagnostics only. They do not assess naturalness, prosody, emotional fit or speaker similarity. Vietnamese token error uses whitespace-delimited syllables. Review full samples before selecting a production voice.\n\n"
        "Supertonic is comparison-only and OpenRAIL-M manual-review-required. Piper source evidence does not establish blanket commercial clearance.\n",
        encoding="utf-8",
    )
    with (output / "human-review.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["language", "engine", "voice_id", "scenario", "naturalness", "pronunciation", "prosody", "emotion", "notes"])
        for row in results:
            writer.writerow([row["language"], row["engine"], row["voice_id"], row["scenario_id"], "", "", "", "", ""])
    archive = output / "tts-candidate-benchmark.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4) as bundle:
        for path in sorted(output.rglob("*")):
            if path.is_file() and path != archive:
                info = zipfile.ZipInfo(path.relative_to(output).as_posix())
                info.date_time = (2020, 1, 1, 0, 0, 0)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                with path.open("rb") as source, bundle.open(info, "w") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
    print(f"[tts-benchmark] COMPLETE {len(results)}/{expected} samples; {len(failures)} failures", flush=True)
    return 0 if results and not failures else 1


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("en", "vi", "both"), default="both")
    parser.add_argument("--asr-model", choices=("base", "small", "medium"), default="small")
    parser.add_argument("--output", default="dist/tts-candidate-benchmark")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
