#!/usr/bin/env python3
"""Benchmark KorvaTTS throughput at different flow-matching step counts."""
from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import html
import importlib.metadata
import importlib.util
import json
import os
import platform
import shutil
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "dogenthq/KorvaTTS"
PACKAGE_VERSION = "0.1.3"
STEPS = (8, 16, 24, 32)
VOICE_IDS = (
    "bao_kim", "gia_bao", "hoang_nam", "huu_dat", "khanh_vy",
    "ngoc_huyen", "phuong_linh", "quang_huy", "quynh_nhu", "thanh_phong",
)
VI_TEXT = (
    "Chào bạn, hôm nay chúng ta sẽ cùng khám phá một câu chuyện mới. "
    "Hãy lắng nghe thật rõ từng chi tiết nhé."
)
SAMPLE_RATE = 44_100
OUTPUT_RATE = 48_000
OUTPUT_BITS = 24
SPEED = 1.05


def check_contract() -> None:
    if len(VOICE_IDS) != 10 or len(set(VOICE_IDS)) != 10:
        raise ValueError("Expected ten unique bundled KorvaTTS voice styles.")
    if STEPS != (8, 16, 24, 32):
        raise ValueError("Step sweep must test 8, 16, 24 and 32 steps.")
    if STEPS[-1] > 32 or STEPS[0] < 1:
        raise ValueError("Step count is outside the KorvaTTS supported range.")
    if not VI_TEXT.strip():
        raise ValueError("Benchmark text must be non-empty.")


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
        return round(value / 1024, 1) if value > 0 else None
    except (ImportError, OSError, ValueError, AttributeError):
        return None


def load_builder():
    path = ROOT / "scripts" / "build_voice_library.py"
    spec = importlib.util.spec_from_file_location("voice_library_builder_for_step_sweep", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load VoiceStudio's audio normalization/watermark helpers.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_review(folder: Path, rows: list[dict[str, Any]]) -> None:
    sections = []
    for row in rows:
        blind_id = html.escape(row["blind_id"])
        filename = html.escape(row["file_name"])
        sections.append(
            f'<section><h2>{blind_id}</h2>'
            f'<audio controls preload="none" src="{filename}"></audio></section>'
        )
    page = (
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>KorvaTTS step sweep review</title>"
        "<style>body{font:16px system-ui;max-width:800px;margin:32px auto;padding:0 18px}"
        "audio{width:100%}section{padding:12px 0;border-bottom:1px solid #ddd}</style>"
        "<h1>Blind Vietnamese quality / speed comparison</h1>"
        "<p>Each voice is rendered at 8, 16, 24 and 32 flow-matching steps. "
        "IDs are anonymous; use the CSV to score naturalness, tones and pronunciation.</p>"
        + "".join(sections) + "</html>"
    )
    (folder / "index.html").write_text(page, encoding="utf-8")
    columns = [
        "blind_id", "naturalness_1_5", "pronunciation_1_5",
        "tones_1_5", "prosody_1_5", "voice_identity_consistency_1_5", "notes",
    ]
    with (folder / "human-review.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({"blind_id": row["blind_id"], **{key: "" for key in columns[1:]}})


def run(output: Path) -> dict[str, Any]:
    import numpy as np
    import soundfile as sf
    from huggingface_hub import HfApi, snapshot_download
    from korvatts import TTS

    check_contract()
    version = importlib.metadata.version("korvatts")
    if version != PACKAGE_VERSION:
        raise RuntimeError(f"Expected korvatts=={PACKAGE_VERSION}, got {version}.")
    revision = HfApi().model_info(MODEL_ID, files_metadata=False).sha
    if not isinstance(revision, str) or len(revision) != 40:
        raise RuntimeError("Could not resolve an immutable model revision.")
    assets = snapshot_download(
        repo_id=MODEL_ID, revision=revision, allow_patterns=["onnx/*", "voice_styles/*"]
    )

    output.mkdir(parents=True, exist_ok=True)
    raw_dir = output / "raw"
    normalized_dir = output / "normalized"
    blind_dir = output / "blind-review"
    analysis_dir = output / "analysis"
    for folder in (raw_dir, normalized_dir, blind_dir, analysis_dir):
        folder.mkdir(parents=True, exist_ok=True)

    print(f"[step-sweep] Loading {MODEL_ID}@{revision}", flush=True)
    started = time.perf_counter()
    tts = TTS(
        assets_dir=assets,
        device="cpu",
        auto_download=False,
        num_threads=max(1, min(4, os.cpu_count() or 1)),
    )
    model_load_seconds = time.perf_counter() - started
    actual_voices = set(tts.list_voices())
    if actual_voices != set(VOICE_IDS):
        raise RuntimeError(f"Unexpected bundled voice roster: {sorted(actual_voices)}")
    if int(tts.sample_rate) != SAMPLE_RATE:
        raise RuntimeError(f"Expected native 44.1 kHz, got {tts.sample_rate} Hz.")

    helper = load_builder()
    rows: list[dict[str, Any]] = []
    mapping: list[dict[str, Any]] = []
    total_compute = 0.0

    for voice_index, voice_id in enumerate(VOICE_IDS):
        shared_seed = 20261102 + voice_index
        for step_count in STEPS:
            blind_id = f"step_{len(rows) + 1:02d}"
            raw = raw_dir / f"{blind_id}.wav"
            normalized = normalized_dir / f"{blind_id}.wav"
            started = time.perf_counter()
            waveform, reported_duration = tts.synthesize(
                text=VI_TEXT,
                voice=voice_id,
                lang="vi",
                total_steps=step_count,
                speed=SPEED,
                seed=shared_seed,
            )
            elapsed = time.perf_counter() - started
            total_compute += elapsed
            audio = np.asarray(waveform, dtype=np.float32).squeeze()
            if audio.ndim != 1 or audio.size == 0 or not np.isfinite(audio).all():
                raise RuntimeError(f"{blind_id}: invalid generated signal.")
            sf.write(str(raw), audio, SAMPLE_RATE, format="WAV", subtype="FLOAT")
            duration = len(audio) / SAMPLE_RATE
            if not 2.0 <= duration <= 60.0:
                raise RuntimeError(f"{blind_id}: implausible duration {duration:.2f}s.")
            helper.run_ffmpeg_normalize(raw, normalized, OUTPUT_RATE, OUTPUT_BITS)
            watermark = helper.watermark_and_verify(
                normalized, OUTPUT_BITS,
                context=f"korvatts.step-sweep.vi.{voice_id}.{step_count}",
            )
            checks = helper.validate_audio(normalized, OUTPUT_RATE, OUTPUT_BITS)
            target = blind_dir / f"{blind_id}.wav"
            shutil.copy2(normalized, target)
            row = {
                "blind_id": blind_id,
                "file_name": target.name,
                "duration_seconds": round(duration, 3),
                "reported_duration_seconds": round(float(reported_duration), 3),
                "generation_seconds": round(elapsed, 3),
                "rtfx_audio_over_compute": round(duration / max(elapsed, 1e-6), 4),
                "rtf_compute_over_audio": round(elapsed / max(duration, 1e-6), 4),
                "sample_rate": OUTPUT_RATE,
                "bits": OUTPUT_BITS,
                "watermark": "verified",
                "watermark_confidence": watermark.get("watermark_confidence"),
                "audio_validation": checks,
                "sha256": sha256(target),
            }
            rows.append(row)
            mapping.append({
                **row,
                "voice_style": voice_id,
                "total_steps": step_count,
                "seed": shared_seed,
                "speed": SPEED,
                "text": VI_TEXT,
            })
            print(
                f"[step-sweep] {blind_id} {voice_id} steps={step_count}: "
                f"{duration:.2f}s audio / {elapsed:.3f}s synth; "
                f"audio/compute={row['rtfx_audio_over_compute']:.3f}; "
                f"RSS={peak_rss_mib()} MiB",
                flush=True,
            )
            raw.unlink(missing_ok=True)
            normalized.unlink(missing_ok=True)

    peak = peak_rss_mib()
    del tts
    gc.collect()
    write_review(blind_dir, rows)
    for folder in (raw_dir, normalized_dir):
        for path in folder.glob("*"):
            path.unlink(missing_ok=True)
        folder.rmdir()

    per_step = {}
    for step_count in STEPS:
        selected = [row for row in mapping if row["total_steps"] == step_count]
        audio_s = sum(row["duration_seconds"] for row in selected)
        compute_s = sum(row["generation_seconds"] for row in selected)
        per_step[str(step_count)] = {
            "samples": len(selected),
            "audio_seconds": round(audio_s, 3),
            "synthesis_seconds": round(compute_s, 3),
            "audio_over_compute": round(audio_s / max(compute_s, 1e-6), 4),
            "compute_over_audio": round(compute_s / max(audio_s, 1e-6), 4),
            "mean_rms": round(
                sum(row["audio_validation"]["rms"] for row in selected) / len(selected), 6
            ),
            "mean_near_silence_ratio": round(
                sum(row["audio_validation"]["near_silence_ratio"] for row in selected) / len(selected), 5
            ),
            "mean_peak": round(
                sum(row["audio_validation"]["peak"] for row in selected) / len(selected), 6
            ),
        }

    summary = {
        "benchmark": "KorvaTTS Vietnamese CPU inference-step sweep",
        "status": "technically_validated_not_human_approved",
        "model_id": MODEL_ID,
        "model_revision": revision,
        "package_version": version,
        "device": "onnx-cpu",
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "logical_cpu_count": os.cpu_count(),
        "threads": max(1, min(4, os.cpu_count() or 1)),
        "model_load_seconds": round(model_load_seconds, 3),
        "peak_rss_mib": peak,
        "voice_count": len(VOICE_IDS),
        "step_counts": list(STEPS),
        "planned_samples": len(VOICE_IDS) * len(STEPS),
        "generated_samples": len(rows),
        "total_audio_seconds": round(sum(row["duration_seconds"] for row in rows), 3),
        "total_synthesis_seconds": round(total_compute, 3),
        "overall_audio_over_compute": round(
            sum(row["duration_seconds"] for row in rows) / max(total_compute, 1e-6), 4
        ),
        "per_step": per_step,
        "human_review": "not_completed",
        "production_promotion": "blocked_pending_blind_native_listener_review_and_source_rights_review",
        "limitations": [
            "Signal metrics, waveform checks and watermark verification do not establish naturalness or pronunciation accuracy.",
            "The same seed is reused within each voice across step counts to reduce latent-noise variation, but changing the solver step count changes the generation trajectory.",
            "Lower step counts may improve speed while reducing prosody, tone or consonant quality; listener review is required.",
            "English quality is outside this Vietnamese-only sweep.",
            "The ten bundled voice styles are not new VoiceStudio contributor identities.",
        ],
        "samples": rows,
    }
    (analysis_dir / "benchmark.json").write_text(
        json.dumps({"summary": summary, "sample_mapping": mapping},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# KorvaTTS inference-step sweep",
        f"- Model revision: {revision}",
        f"- Model load: {model_load_seconds:.2f}s",
        f"- Peak RSS: {peak if peak is not None else 'unavailable'} MiB",
        f"- Presets: {len(VOICE_IDS)}",
        f"- Total samples: {len(rows)}",
        f"- Total audio: {summary['total_audio_seconds']:.2f}s",
        f"- Total compute: {total_compute:.2f}s",
        f"- Overall audio/compute: {summary['overall_audio_over_compute']:.3f}x",
        "",
        "| Steps | Samples | Audio (s) | Compute (s) | Audio/compute | Compute/audio | Mean RMS | Mean near-silence |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for step_count in STEPS:
        row = per_step[str(step_count)]
        lines.append(
            f"| {step_count} | {row['samples']} | {row['audio_seconds']:.2f} | "
            f"{row['synthesis_seconds']:.2f} | {row['audio_over_compute']:.3f}x | "
            f"{row['compute_over_audio']:.3f}x | {row['mean_rms']:.4f} | "
            f"{row['mean_near_silence_ratio']:.3f} |"
        )
    lines.extend(["", "Human review is incomplete; no quality grade is assigned."])
    (output / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("dist/korvatts-step-sweep"))
    args = parser.parse_args()
    if args.check:
        check_contract()
        print("KorvaTTS inference-step sweep static check: OK")
        return 0
    run(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
