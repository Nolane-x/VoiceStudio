#!/usr/bin/env python3
"""Stress-test Vietnamese KorvaTTS quality/speed over text types and step counts."""
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
VOICE_IDS = ("bao_kim", "gia_bao", "ngoc_huyen", "hoang_nam", "thanh_phong")
STEP_COUNTS = (8, 16, 32)
TEXT_CASES = {
    "natural_tones": (
        "Chào bạn, hôm nay chúng ta sẽ cùng khám phá một câu chuyện mới. "
        "Hãy lắng nghe thật rõ từng chi tiết nhé."
    ),
    "numbers_names": (
        "Vào lúc 7 giờ 45 phút sáng ngày 3 tháng 11 năm 2026, "
        "Nguyễn Minh Anh ghi nhận nhiệt độ 36,8 độ C tại Hải Phòng. "
        "Mã hồ sơ là HP-2048 và số điện thoại kết thúc bằng 0912."
    ),
    "vietnamese_code_switch": (
        "Nhóm nghiên cứu vừa cập nhật dashboard trên GitHub Actions. "
        "Bản demo dùng Python, ONNX Runtime và text-to-speech offline, "
        "sau đó xuất file WAV 48 kHz để kiểm tra chất lượng."
    ),
}
SAMPLE_RATE = 44_100
OUTPUT_RATE = 48_000
OUTPUT_BITS = 24
SPEED = 1.05


def check_contract() -> None:
    if len(VOICE_IDS) != 5 or len(set(VOICE_IDS)) != 5:
        raise ValueError("Expected five distinct bundled voice styles.")
    if STEP_COUNTS != (8, 16, 32):
        raise ValueError("Stress comparison must cover 8, 16 and 32 steps.")
    if set(TEXT_CASES) != {"natural_tones", "numbers_names", "vietnamese_code_switch"}:
        raise ValueError("Expected all three Vietnamese text stress cases.")
    if not all(text.strip() for text in TEXT_CASES.values()):
        raise ValueError("Text stress cases cannot be empty.")


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
    spec = importlib.util.spec_from_file_location("voice_library_builder_for_korva_stress", path)
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
        name = html.escape(row["file_name"])
        sections.append(
            f'<section><h2>{blind_id}</h2><audio controls preload="none" src="{name}"></audio></section>'
        )
    page = (
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>KorvaTTS Vietnamese stress listening review</title>"
        "<style>body{font:16px system-ui;max-width:800px;margin:32px auto;padding:0 18px}"
        "audio{width:100%}section{padding:12px 0;border-bottom:1px solid #ddd}</style>"
        "<h1>Blind Vietnamese TTS stress review</h1>"
        "<p>Samples cover natural speech, dates/numbers/names, and English terms embedded in Vietnamese.</p>"
        + "".join(sections) + "</html>"
    )
    (folder / "index.html").write_text(page, encoding="utf-8")
    columns = [
        "blind_id", "naturalness_1_5", "tone_accuracy_1_5",
        "number_name_pronunciation_1_5", "code_switching_1_5",
        "prosody_1_5", "notes",
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
        raise RuntimeError("Could not resolve immutable model revision.")
    assets = snapshot_download(
        repo_id=MODEL_ID, revision=revision, allow_patterns=["onnx/*", "voice_styles/*"]
    )

    output.mkdir(parents=True, exist_ok=True)
    raw_dir, normalized_dir, blind_dir, analysis_dir = (
        output / "raw", output / "normalized", output / "blind-review", output / "analysis"
    )
    for folder in (raw_dir, normalized_dir, blind_dir, analysis_dir):
        folder.mkdir(parents=True, exist_ok=True)

    start_load = time.perf_counter()
    tts = TTS(
        assets_dir=assets,
        device="cpu",
        auto_download=False,
        num_threads=max(1, min(4, os.cpu_count() or 1)),
    )
    model_load = time.perf_counter() - start_load
    if set(tts.list_voices()) < set(VOICE_IDS):
        raise RuntimeError("Some selected bundled voices are missing.")
    if int(tts.sample_rate) != SAMPLE_RATE:
        raise RuntimeError(f"Expected 44.1kHz native output, got {tts.sample_rate}Hz.")

    helper = load_builder()
    rows: list[dict[str, Any]] = []
    mapping: list[dict[str, Any]] = []
    total_compute = 0.0
    for voice_index, voice in enumerate(VOICE_IDS):
        for case_index, (case_name, text) in enumerate(TEXT_CASES.items()):
            shared_seed = 20261103 + voice_index * 100 + case_index
            for steps in STEP_COUNTS:
                blind_id = f"stress_{len(rows) + 1:02d}"
                raw = raw_dir / f"{blind_id}.wav"
                normalized = normalized_dir / f"{blind_id}.wav"
                started = time.perf_counter()
                waveform, duration_reported = tts.synthesize(
                    text=text,
                    voice=voice,
                    lang="vi",
                    total_steps=steps,
                    speed=SPEED,
                    seed=shared_seed,
                )
                elapsed = time.perf_counter() - started
                total_compute += elapsed
                audio = np.asarray(waveform, dtype=np.float32).squeeze()
                if audio.ndim != 1 or audio.size == 0 or not np.isfinite(audio).all():
                    raise RuntimeError(f"{blind_id}: invalid waveform.")
                sf.write(str(raw), audio, SAMPLE_RATE, format="WAV", subtype="FLOAT")
                duration = len(audio) / SAMPLE_RATE
                if not 2 <= duration <= 90:
                    raise RuntimeError(f"{blind_id}: implausible duration {duration:.2f}s.")
                helper.run_ffmpeg_normalize(raw, normalized, OUTPUT_RATE, OUTPUT_BITS)
                watermark = helper.watermark_and_verify(
                    normalized, OUTPUT_BITS,
                    context=f"korvatts.stress.{case_name}.{voice}.{steps}",
                )
                checks = helper.validate_audio(normalized, OUTPUT_RATE, OUTPUT_BITS)
                target = blind_dir / f"{blind_id}.wav"
                shutil.copy2(normalized, target)
                row = {
                    "blind_id": blind_id,
                    "file_name": target.name,
                    "duration_seconds": round(duration, 3),
                    "generation_seconds": round(elapsed, 3),
                    "audio_over_compute": round(duration / max(elapsed, 1e-6), 4),
                    "compute_over_audio": round(elapsed / max(duration, 1e-6), 4),
                    "watermark": "verified",
                    "watermark_confidence": watermark.get("watermark_confidence"),
                    "audio_validation": checks,
                    "sha256": sha256(target),
                }
                rows.append(row)
                mapping.append({
                    **row,
                    "voice_style": voice,
                    "text_case": case_name,
                    "total_steps": steps,
                    "seed": shared_seed,
                    "text": text,
                })
                print(
                    f"[stress] {blind_id} {voice} {case_name} steps={steps}: "
                    f"{duration:.2f}s / {elapsed:.2f}s; "
                    f"audio/compute={row['audio_over_compute']:.3f}; RSS={peak_rss_mib()} MiB",
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

    aggregate = {}
    for steps in STEP_COUNTS:
        selected = [r for r in mapping if r["total_steps"] == steps]
        audio_s = sum(r["duration_seconds"] for r in selected)
        compute_s = sum(r["generation_seconds"] for r in selected)
        aggregate[str(steps)] = {
            "samples": len(selected),
            "audio_seconds": round(audio_s, 3),
            "synthesis_seconds": round(compute_s, 3),
            "audio_over_compute": round(audio_s / max(compute_s, 1e-6), 4),
            "compute_over_audio": round(compute_s / max(audio_s, 1e-6), 4),
        }

    by_case = {}
    for case_name in TEXT_CASES:
        by_case[case_name] = {}
        for steps in STEP_COUNTS:
            selected = [
                r for r in mapping
                if r["text_case"] == case_name and r["total_steps"] == steps
            ]
            audio_s = sum(r["duration_seconds"] for r in selected)
            compute_s = sum(r["generation_seconds"] for r in selected)
            by_case[case_name][str(steps)] = {
                "samples": len(selected),
                "audio_seconds": round(audio_s, 3),
                "synthesis_seconds": round(compute_s, 3),
                "audio_over_compute": round(audio_s / max(compute_s, 1e-6), 4),
                "compute_over_audio": round(compute_s / max(audio_s, 1e-6), 4),
                "mean_near_silence_ratio": round(
                    sum(r["audio_validation"]["near_silence_ratio"] for r in selected)
                    / len(selected), 5
                ),
            }

    summary = {
        "benchmark": "KorvaTTS Vietnamese text-case / inference-step stress matrix",
        "status": "technically_validated_not_human_approved",
        "model_id": MODEL_ID,
        "model_revision": revision,
        "package_version": version,
        "device": "onnx-cpu",
        "model_load_seconds": round(model_load, 3),
        "peak_rss_mib": peak,
        "voice_count": len(VOICE_IDS),
        "text_case_count": len(TEXT_CASES),
        "step_counts": list(STEP_COUNTS),
        "planned_samples": len(VOICE_IDS) * len(TEXT_CASES) * len(STEP_COUNTS),
        "generated_samples": len(rows),
        "total_audio_seconds": round(sum(r["duration_seconds"] for r in rows), 3),
        "total_synthesis_seconds": round(total_compute, 3),
        "overall_audio_over_compute": round(
            sum(r["duration_seconds"] for r in rows) / max(total_compute, 1e-6), 4
        ),
        "per_step": aggregate,
        "per_text_case": by_case,
        "human_review": "not_completed",
        "production_promotion": "blocked_pending_blind_native_listener_review_and_source_rights_review",
        "limitations": [
            "Only five of ten presets are included in this stress matrix.",
            "Automatic signal checks and watermarking do not prove naturalness, tone accuracy or intelligibility.",
            "All text cases are Vietnamese, including embedded English terms.",
            "Step-count differences must be reviewed by human listening before selecting a production setting.",
            "No new speaker identities or contributor recordings are introduced.",
        ],
        "samples": rows,
    }
    (analysis_dir / "benchmark.json").write_text(
        json.dumps({"summary": summary, "sample_mapping": mapping},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# KorvaTTS Vietnamese stress matrix",
        f"- Model revision: {revision}",
        f"- Model load: {model_load:.2f}s",
        f"- Peak RSS: {peak if peak is not None else 'unavailable'} MiB",
        f"- Presets: {len(VOICE_IDS)}",
        f"- Text cases: {len(TEXT_CASES)}",
        f"- Samples: {len(rows)}",
        f"- Audio: {summary['total_audio_seconds']:.2f}s",
        f"- Compute: {total_compute:.2f}s",
        "",
        "| Text case | Steps | Samples | Audio (s) | Compute (s) | Audio/compute |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for case_name in TEXT_CASES:
        for steps in STEP_COUNTS:
            row = by_case[case_name][str(steps)]
            lines.append(
                f"| {case_name} | {steps} | {row['samples']} | "
                f"{row['audio_seconds']:.2f} | {row['synthesis_seconds']:.2f} | "
                f"{row['audio_over_compute']:.3f}x |"
            )
    lines.extend(["", "Human review is incomplete; no quality grade is assigned."])
    (output / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("dist/korvatts-stress"))
    args = parser.parse_args()
    if args.check:
        check_contract()
        print("KorvaTTS stress matrix static check: OK")
        return 0
    run(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
