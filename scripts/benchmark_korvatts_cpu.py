#!/usr/bin/env python3
"""VoiceStudio CPU feasibility benchmark for KorvaTTS."""
from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "dogenthq/KorvaTTS"
PACKAGE_VERSION = "0.1.3"
VOICES = (
    "bao_kim", "gia_bao", "hoang_nam", "huu_dat", "khanh_vy",
    "ngoc_huyen", "phuong_linh", "quynh_nhu", "quang_huy", "thanh_phong",
)
VI_TEXT = "Chào bạn, hôm nay chúng ta sẽ cùng khám phá một câu chuyện mới. Hãy lắng nghe thật rõ từng chi tiết nhé."
MIXED_TEXT = "Chào bạn, hôm nay nhóm mình sẽ demo công nghệ text-to-speech chạy hoàn toàn offline trên CPU."
EN_TEXT = "Hello and welcome. Today we are exploring a new story. Please listen closely to every detail."
DIAGNOSTIC_VOICES = ("bao_kim", "gia_bao")


def check_contract() -> None:
    if len(VOICES) != 10 or len(set(VOICES)) != 10:
        raise ValueError("Expected exactly ten distinct KorvaTTS voice styles.")
    if not all((VI_TEXT, MIXED_TEXT, EN_TEXT)):
        raise ValueError("Benchmark text cannot be empty.")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def peak_rss_mib() -> float | None:
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(value / (1024 if sys.platform != "darwin" else 1024 * 1024), 1)
    except (ImportError, OSError, ValueError, AttributeError):
        return None


def load_builder():
    path = ROOT / "scripts" / "build_voice_library.py"
    spec = importlib.util.spec_from_file_location("voice_library_builder_for_korva", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load VoiceStudio audio helpers.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_review(folder: Path, rows: list[dict]) -> None:
    import html
    sections = []
    for row in rows:
        sample = html.escape(row["blind_id"])
        filename = html.escape(row["file_name"])
        sections.append(
            f'<section><h2>{sample}</h2><audio controls preload="none" src="{filename}"></audio></section>'
        )
    page = (
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><title>Blind audio review</title>"
        "<style>body{font:16px system-ui;max-width:760px;margin:32px auto;padding:0 18px}"
        "audio{width:100%}</style><h1>Anonymous listening review</h1>"
        + "".join(sections) + "</html>"
    )
    (folder / "index.html").write_text(page, encoding="utf-8")
    columns = ["blind_id", "language", "naturalness_1_5", "pronunciation_1_5", "prosody_1_5", "notes"]
    with (folder / "human-review.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") if key in row else "" for key in columns})


def run(output: Path) -> dict:
    import numpy as np
    import soundfile as sf
    from huggingface_hub import HfApi, snapshot_download
    from korvatts import TTS

    check_contract()
    version = importlib.metadata.version("korvatts")
    if version != PACKAGE_VERSION:
        raise RuntimeError(f"Expected korvatts=={PACKAGE_VERSION}, got {version}")
    revision = HfApi().model_info(MODEL_ID, files_metadata=False).sha
    if not isinstance(revision, str) or len(revision) != 40:
        raise RuntimeError("Could not pin model to an immutable 40-character revision.")
    assets = snapshot_download(
        repo_id=MODEL_ID, revision=revision, allow_patterns=["onnx/*", "voice_styles/*"]
    )

    output.mkdir(parents=True, exist_ok=True)
    raw_dir, normalized_dir, blind_dir, analysis_dir = (
        output / "raw", output / "normalized", output / "blind-review", output / "analysis"
    )
    for folder in (raw_dir, normalized_dir, blind_dir, analysis_dir):
        folder.mkdir(parents=True, exist_ok=True)

    print(f"[KorvaTTS] Loading pinned revision {revision}", flush=True)
    started = time.perf_counter()
    tts = TTS(
        assets_dir=assets, device="cpu", auto_download=False,
        num_threads=max(1, min(4, os.cpu_count() or 1)),
    )
    load_seconds = time.perf_counter() - started
    if tuple(sorted(tts.list_voices())) != tuple(sorted(VOICES)):
        raise RuntimeError(f"Voice roster changed: {tts.list_voices()}")
    if int(tts.sample_rate) != 44100:
        raise RuntimeError(f"Expected native 44.1kHz, got {tts.sample_rate}")

    helper = load_builder()
    rows, mapping = [], []
    total_compute = 0.0

    def synthesize(voice: str, language: str, text: str, seed: int) -> None:
        nonlocal total_compute
        blind_id = f"sample_{len(rows) + 1:02d}"
        raw = raw_dir / f"{blind_id}.wav"
        normalized = normalized_dir / f"{blind_id}.wav"
        t0 = time.perf_counter()
        waveform, reported_duration = tts.synthesize(
            text=text, voice=voice, lang=language, total_steps=32, speed=1.05, seed=seed
        )
        elapsed = time.perf_counter() - t0
        total_compute += elapsed
        samples = np.asarray(waveform, dtype=np.float32).squeeze()
        if samples.ndim != 1 or not samples.size or not np.isfinite(samples).all():
            raise RuntimeError(f"{blind_id}: invalid generated signal")
        sf.write(str(raw), samples, 44100, format="WAV", subtype="FLOAT")
        duration = len(samples) / 44100
        if not 2 <= duration <= 60:
            raise RuntimeError(f"{blind_id}: invalid duration {duration:.2f}s")
        helper.run_ffmpeg_normalize(raw, normalized, 48000, 24)
        watermark = helper.watermark_and_verify(
            normalized, 24, context=f"korvatts.cpu.{language}"
        )
        checks = helper.validate_audio(normalized, 48000, 24)
        target = blind_dir / f"{blind_id}.wav"
        shutil.copy2(normalized, target)
        row = {
            "blind_id": blind_id, "language": language, "file_name": target.name,
            "duration_seconds": round(duration, 3),
            "reported_duration_seconds": round(float(reported_duration), 3),
            "generation_seconds": round(elapsed, 3),
            "rtfx": round(duration / max(elapsed, 1e-6), 4),
            "watermark": "verified",
            "watermark_confidence": watermark.get("watermark_confidence"),
            "audio_validation": checks, "sha256": sha256(target),
        }
        rows.append(row)
        mapping.append({**row, "voice_style": voice, "text": text, "seed": seed})
        print(
            f"[KorvaTTS] {blind_id} {language}/{voice}: {duration:.2f}s / "
            f"{elapsed:.2f}s; RTFx={row['rtfx']:.3f}; RSS={peak_rss_mib()} MiB",
            flush=True,
        )
        raw.unlink(missing_ok=True)
        normalized.unlink(missing_ok=True)

    for index, voice in enumerate(VOICES, 1):
        synthesize(voice, "vi", VI_TEXT, 20261120 + index)

    diagnostics = []
    for index, voice in enumerate(DIAGNOSTIC_VOICES, 1):
        for language, text in (("vi", MIXED_TEXT), ("en", EN_TEXT)):
            try:
                synthesize(voice, language, text, 20261200 + index)
                diagnostics.append({"voice": voice, "language": language, "status": "generated"})
            except Exception as exc:
                diagnostics.append(
                    {"voice": voice, "language": language, "status": "failed",
                     "reason": f"{type(exc).__name__}: {str(exc)[:300]}"}
                )
                print(f"[KorvaTTS] diagnostic failed: {language}/{voice}: {exc}", flush=True)

    peak = peak_rss_mib()
    del tts
    gc.collect()
    write_review(blind_dir, rows)
    for folder in (raw_dir, normalized_dir):
        for path in folder.glob("*"):
            path.unlink(missing_ok=True)
        folder.rmdir()

    summary = {
        "benchmark": "VoiceStudio local KorvaTTS CPU feasibility",
        "status": "technically_validated_not_human_approved",
        "model_id": MODEL_ID, "model_revision": revision,
        "package": "korvatts", "package_version": version,
        "model_license": "Apache-2.0 as published by model authors",
        "device": "onnx-cpu", "python_version": platform.python_version(),
        "platform": platform.platform(), "logical_cpu_count": os.cpu_count(),
        "model_load_seconds": round(load_seconds, 3), "peak_rss_mib": peak,
        "native_sample_rate": 44100, "output_sample_rate": 48000, "output_bits": 24,
        "voice_style_count": len(VOICES), "primary_vietnamese_samples": len(VOICES),
        "diagnostic_sample_count": len(rows) - len(VOICES), "samples": rows,
        "cross_language_diagnostics": diagnostics,
        "total_synthesis_seconds": round(total_compute, 3),
        "total_audio_seconds": round(sum(r["duration_seconds"] for r in rows), 3),
        "overall_rtfx": round(sum(r["duration_seconds"] for r in rows) / max(total_compute, 1e-6), 4),
        "human_review": "not_completed",
        "production_promotion": "blocked_pending_training_data_and_voice_source_rights_review_and_native_listener_review",
        "rights_notes": [
            "The model publisher labels code, weights and voice styles Apache-2.0.",
            "The publisher says training used a filtered subset of PhoAudiobook and a private code-switching corpus.",
            "PhoAudiobook's agreement restricts dataset use to research/education and forbids redistribution of the dataset or parts; that is separate from the model's published license.",
            "Do not promote this benchmark as production-cleared until training-data and bundled speaker/source-voice permissions are reviewed.",
        ],
        "limitations": [
            "Bundled styles are not new VoiceStudio contributor identities.",
            "English probes are exploratory; upstream does not guarantee English quality.",
            "Signal checks and watermarking do not measure naturalness, Vietnamese tones, accent, pronunciation or listener preference.",
            "No model weights or original recordings are included in the artifact.",
        ],
    }
    (analysis_dir / "benchmark.json").write_text(
        json.dumps({"summary": summary, "voice_style_ids": VOICES, "sample_mapping": mapping},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report = [
        "# KorvaTTS local CPU benchmark",
        f"- Model revision: {revision}",
        f"- Model load: {load_seconds:.2f}s",
        f"- Peak RSS: {peak if peak is not None else 'unavailable'} MiB",
        f"- Main Vietnamese styles: {len(VOICES)}",
        f"- Diagnostic samples: {len(rows) - len(VOICES)}",
        f"- Total audio: {summary['total_audio_seconds']:.2f}s",
        f"- Compute: {total_compute:.2f}s",
        f"- Overall RTFx: {summary['overall_rtfx']:.3f}",
        "", "| ID | Lang | Audio (s) | Compute (s) | RTFx |", "|---|---|---:|---:|---:|",
    ]
    report.extend(
        f"| {r['blind_id']} | {r['language']} | {r['duration_seconds']:.2f} | "
        f"{r['generation_seconds']:.2f} | {r['rtfx']:.3f} |" for r in rows
    )
    report.extend(["", "Human listening and data/voice rights review remain incomplete."])
    (output / "SUMMARY.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("dist/korvatts-cpu"))
    args = parser.parse_args()
    if args.check:
        check_contract()
        print("KorvaTTS local CPU benchmark static check: OK")
        return 0
    run(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
