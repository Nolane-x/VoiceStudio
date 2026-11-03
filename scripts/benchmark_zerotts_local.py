#!/usr/bin/env python3
"""VoiceStudio local CPU screening benchmark for ZeroTTS Vietnamese ONNX TTS."""
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
import random
import shutil
import shutil
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "zeroweight-ai/ZeroTTS"
PACKAGE_VERSION = "0.1.5"
EXPECTED_VOICES = (
    "maichi",
    "baotrang",
    "kimoanh",
    "hamy",
    "giahuy",
    "huuduc",
    "quangminh",
    "tiendat",
)
TEXT_CASES = {
    "natural_vietnamese": (
        "Chào bạn, hôm nay chúng ta sẽ cùng khám phá một câu chuyện mới. "
        "Hãy lắng nghe thật rõ từng chi tiết nhé."
    ),
    "numbers_names_raw": (
        "Ngày 03/11/2026, Nguyễn Minh Anh ghi nhận nhiệt độ 36,8 độ C "
        "tại Hải Phòng. Mã hồ sơ là HP-2048."
    ),
    "numbers_names_normalized": (
        "Ngày 03/11/2026, Nguyễn Minh Anh ghi nhận nhiệt độ 36,8 độ C "
        "tại Hải Phòng. Mã hồ sơ là HP-2048."
    ),
    "vietnamese_code_switch": (
        "Nhóm nghiên cứu vừa cập nhật dashboard trên GitHub Actions. "
        "Bản demo dùng Python, ONNX Runtime và text-to-speech offline, "
        "sau đó xuất file WAV 48 kHz để kiểm tra chất lượng."
    ),
}
STREAM_TEXT = (
    "Đây là phép thử phát âm thanh trực tuyến. Âm thanh đầu tiên cần xuất hiện "
    "sớm, sau đó các phần tiếp theo sẽ được tạo liên tục mà không cần đợi "
    "toàn bộ đoạn văn hoàn tất."
)
SAMPLE_RATE = 48_000
OUTPUT_RATE = 48_000
OUTPUT_BITS = 24
THREADS = max(1, min(4, os.cpu_count() or 1))


def check_contract() -> None:
    if len(EXPECTED_VOICES) != 8 or len(set(EXPECTED_VOICES)) != 8:
        raise ValueError("ZeroTTS benchmark must cover exactly eight bundled presets.")
    if len(TEXT_CASES) != 4 or not all(text.strip() for text in TEXT_CASES.values()):
        raise ValueError("Expected four non-empty Vietnamese text test cases.")
    if SAMPLE_RATE != 48_000 or OUTPUT_RATE != 48_000 or OUTPUT_BITS != 24:
        raise ValueError("Unexpected ZeroTTS audio output contract.")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def peak_rss_mib() -> float | None:
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if value <= 0:
            return None
        if sys.platform == "darwin":
            return round(value / (1024 * 1024), 1)
        return round(value / 1024, 1)
    except (ImportError, OSError, ValueError, AttributeError):
        return None


def load_builder():
    path = ROOT / "scripts" / "build_voice_library.py"
    spec = importlib.util.spec_from_file_location("zerotts_voice_library_builder", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load VoiceStudio audio normalization/watermark helpers.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_blind_review(folder: Path, rows: list[dict[str, Any]]) -> None:
    review_rows = [
        {
            "blind_id": row["blind_id"],
            "file_name": row["file_name"],
        }
        for row in rows
    ]
    random.Random(20261103).shuffle(review_rows)
    sections = []
    for row in review_rows:
        blind_id = html.escape(row["blind_id"])
        filename = html.escape(row["file_name"])
        sections.append(
            f'<section><h2>{blind_id}</h2>'
            f'<audio controls preload="none" src="{filename}"></audio></section>'
        )
    page = (
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>ZeroTTS anonymous Vietnamese listening review</title>"
        "<style>body{font:16px system-ui;max-width:800px;margin:32px auto;padding:0 18px}"
        "audio{width:100%}section{padding:16px 0;border-bottom:1px solid #ddd}</style>"
        "<h1>Anonymous ZeroTTS Vietnamese listening review</h1>"
        "<p>Rate tone accuracy, naturalness, numbers and names, code-switching, "
        "and streaming quality. Sample metadata is deliberately withheld.</p>"
        + "".join(sections)
        + "</html>"
    )
    (folder / "index.html").write_text(page, encoding="utf-8")

    columns = [
        "blind_id",
        "naturalness_1_5",
        "tone_accuracy_1_5",
        "number_name_pronunciation_1_5",
        "code_switching_1_5",
        "prosody_1_5",
        "streaming_continuity_1_5",
        "notes",
    ]
    with (folder / "human-review.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in review_rows:
            writer.writerow({"blind_id": row["blind_id"], **{key: "" for key in columns[1:]}})


def run(output: Path) -> dict[str, Any]:
    import numpy as np
    import soundfile as sf
    from huggingface_hub import HfApi, snapshot_download
    import zerotts
    from zerotts import ZeroTTS, normalize_vi_text

    check_contract()
    installed_version = importlib.metadata.version("zerotts")
    if installed_version != PACKAGE_VERSION:
        raise RuntimeError(
            f"Expected the provenance-pinned zerotts=={PACKAGE_VERSION}, got {installed_version}."
        )
    package_module_version = str(getattr(zerotts, "__version__", "unknown"))

    revision = HfApi().model_info(MODEL_ID, files_metadata=False).sha
    if not isinstance(revision, str) or len(revision) != 40:
        raise RuntimeError("Hugging Face did not return an immutable 40-character model revision.")

    snapshot_dir = Path(snapshot_download(
        repo_id=MODEL_ID,
        revision=revision,
        allow_patterns=[
            "config.json",
            "tokenizer.json",
            "null_voice_emb.npy",
            "silence_frame.npy",
            "onnx/*",
            "onnx/codec/*",
            "voices/index.json",
            "voices/*/voice.npz",
            "voices/*/meta.json",
            "voices/*/preview.wav",
        ],
    ))
    materialized_model = Path("/tmp/zerotts-model-materialized")
    if materialized_model.exists():
        shutil.rmtree(materialized_model)
    # HF cache snapshots contain file symlinks to separate blob directories.
    # Some ONNX graphs use external .data sidecars; resolving the graph symlink
    # makes ONNX Runtime treat the sidecar as an unsafe path escape. Copy the
    # snapshot as ordinary files so the graph and each sidecar remain siblings.
    print(f"[ZeroTTS] Materializing model snapshot from {snapshot_dir}", flush=True)
    shutil.copytree(snapshot_dir, materialized_model, symlinks=False)
    if not (materialized_model / "onnx" / "codec").is_dir():
        raise RuntimeError("Materialized model is missing the ONNX codec directory.")
    print(
        f"[ZeroTTS] Materialized model size: "
        f"{sum(p.stat().st_size for p in materialized_model.rglob('*') if p.is_file()) / (1024**2):.1f} MiB",
        flush=True,
    )

    output.mkdir(parents=True, exist_ok=True)
    raw_dir = output / "raw"
    normalized_dir = output / "normalized"
    blind_dir = output / "blind-review"
    analysis_dir = output / "analysis"
    for folder in (raw_dir, normalized_dir, blind_dir, analysis_dir):
        folder.mkdir(parents=True, exist_ok=True)

    print(
        f"[ZeroTTS] Loading {MODEL_ID}@{revision} with ONNX CPU provider, "
        f"{THREADS} intra-op threads",
        flush=True,
    )
    load_started = time.perf_counter()
    tts = ZeroTTS.from_pretrained(
        materialized_model,
        providers=["CPUExecutionProvider"],
        intra_op_num_threads=THREADS,
        codec_intra_op_num_threads=THREADS,
        warmup=False,
    )
    model_load_seconds = time.perf_counter() - load_started

    if int(tts.sample_rate) != SAMPLE_RATE:
        raise RuntimeError(f"Expected 48 kHz native output, got {tts.sample_rate} Hz.")
    available_voices = set(tts.list_voices())
    missing_voices = set(EXPECTED_VOICES) - available_voices
    if missing_voices:
        raise RuntimeError(f"Bundled ZeroTTS presets are missing: {sorted(missing_voices)}")

    warmup_started = time.perf_counter()
    tts.warmup()
    warmup_seconds = time.perf_counter() - warmup_started
    print(
        f"[ZeroTTS] Loaded in {model_load_seconds:.2f}s; warm-up {warmup_seconds:.2f}s; "
        f"voices={len(available_voices)}; sample_rate={tts.sample_rate}",
        flush=True,
    )

    rows: list[dict[str, Any]] = []
    mapping: list[dict[str, Any]] = []
    total_one_shot_seconds = 0.0
    stream_total_seconds = 0.0

    def save_raw(
        blind_id: str,
        audio: Any,
        voice: str,
        case_name: str,
        text: str,
        seed: int,
        mode: str,
        generation_seconds: float,
        audio_duration: float,
        extra: dict[str, Any] | None = None,
    ) -> None:
        raw_path = raw_dir / f"{blind_id}.wav"
        waveform = np.asarray(audio, dtype=np.float32).squeeze()
        if waveform.ndim != 1 or waveform.size == 0 or not np.isfinite(waveform).all():
            raise RuntimeError(f"{blind_id}: ZeroTTS returned an invalid waveform.")
        measured_duration = len(waveform) / SAMPLE_RATE
        if measured_duration < 1.0 or measured_duration > 120.0:
            raise RuntimeError(
                f"{blind_id}: implausible waveform duration {measured_duration:.2f}s."
            )
        sf.write(
            str(raw_path),
            waveform,
            SAMPLE_RATE,
            format="WAV",
            subtype="FLOAT",
        )
        row = {
            "blind_id": blind_id,
            "raw_path": str(raw_path),
            "language": "vi",
            "mode": mode,
            "voice": voice,
            "text_case": case_name,
            "text": text,
            "seed": seed,
            "duration_seconds": round(measured_duration, 3),
            "reported_duration_seconds": round(float(audio_duration), 3),
            "generation_seconds": round(generation_seconds, 3),
            "audio_over_compute": round(measured_duration / max(generation_seconds, 1e-6), 4),
            "compute_over_audio": round(generation_seconds / max(measured_duration, 1e-6), 4),
        }
        if extra:
            row.update(extra)
        mapping.append(row)
        print(
            f"[ZeroTTS] {blind_id} {voice}/{case_name}/{mode}: "
            f"{measured_duration:.2f}s audio / {generation_seconds:.3f}s compute; "
            f"audio/compute={row['audio_over_compute']:.3f}",
            flush=True,
        )

    for voice_index, voice in enumerate(EXPECTED_VOICES):
        for case_index, (case_name, original_text) in enumerate(TEXT_CASES.items()):
            text = (
                normalize_vi_text(original_text)
                if case_name == "numbers_names_normalized"
                else original_text
            )
            seed = 20261103 + voice_index * 100 + case_index
            blind_id = f"oneshot_{len(rows) + 1:03d}"

            timing: dict[str, Any] = {}
            np.random.seed(seed)
            started = time.perf_counter()
            audio = tts.synthesize(text, voice=voice, timing=timing)
            elapsed = time.perf_counter() - started
            total_one_shot_seconds += elapsed
            duration = np.asarray(audio).shape[-1] / SAMPLE_RATE
            rows.append({
                "blind_id": blind_id,
                "raw_path": "",
                "voice": voice,
                "case_name": case_name,
                "mode": "one_shot",
                "duration_seconds": round(float(duration), 3),
            })
            save_raw(
                blind_id,
                audio,
                voice,
                case_name,
                text,
                seed,
                "one_shot",
                elapsed,
                duration,
                {
                    "time_to_first_frame_seconds": timing.get("time_to_first_frame"),
                    "frame_generation_seconds": timing.get("total_time"),
                    "generated_frames": timing.get("n_frames"),
                },
            )

    for voice_index, voice in enumerate(EXPECTED_VOICES):
        blind_id = f"stream_{voice_index + 1:03d}"
        seed = 20261203 + voice_index
        np.random.seed(seed)
        stream = iter(
            tts.synthesize_stream(
                STREAM_TEXT,
                voice=voice,
                first_chunk_frames=1,
                max_chunk_frames=16,
            )
        )
        chunks = []
        started = time.perf_counter()
        try:
            first_chunk = next(stream)
        except StopIteration as exc:
            raise RuntimeError(f"{blind_id}: ZeroTTS streaming returned no audio.") from exc
        time_to_first_audio_seconds = time.perf_counter() - started
        chunks.append(np.asarray(first_chunk, dtype=np.float32))
        try:
            for chunk in stream:
                chunks.append(np.asarray(chunk, dtype=np.float32))
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
        elapsed = time.perf_counter() - started
        stream_total_seconds += elapsed
        audio = np.concatenate(chunks, axis=-1)
        save_raw(
            blind_id,
            audio,
            voice,
            "streaming_natural",
            STREAM_TEXT,
            seed,
            "streaming",
            elapsed,
            audio.shape[-1] / SAMPLE_RATE,
            {
                "time_to_first_audio_seconds": time_to_first_audio_seconds,
                "first_chunk_duration_seconds": round(first_chunk.shape[-1] / SAMPLE_RATE, 4),
                "stream_chunk_count": len(chunks),
            },
        )

    peak_rss_during_tts = peak_rss_mib()
    print(
        f"[ZeroTTS] TTS complete: one-shot={total_one_shot_seconds:.2f}s, "
        f"streaming={stream_total_seconds:.2f}s, peak RSS={peak_rss_during_tts} MiB",
        flush=True,
    )
    del tts
    gc.collect()

    # The audio watermark/FFmpeg helpers load the heavier provenance stack.
    # Import them only after TTS generation so peak_rss_during_tts reflects the
    # ONNX inference process rather than optional watermark tooling.
    builder = load_builder()
    for row in mapping:
        raw_path = Path(row["raw_path"])
        normalized_path = normalized_dir / f"{row['blind_id']}.wav"
        target = blind_dir / f"{row['blind_id']}.wav"
        builder.run_ffmpeg_normalize(raw_path, normalized_path, OUTPUT_RATE, OUTPUT_BITS)
        watermark = builder.watermark_and_verify(
            normalized_path,
            OUTPUT_BITS,
            context=f"zerotts.local_cpu.{row['mode']}.{row['voice']}.{row['text_case']}",
        )
        validation = builder.validate_audio(normalized_path, OUTPUT_RATE, OUTPUT_BITS)
        shutil.copy2(normalized_path, target)
        row.update({
            "file_name": target.name,
            "output_sample_rate": OUTPUT_RATE,
            "output_bits": OUTPUT_BITS,
            "watermark": "verified",
            "watermark_confidence": watermark.get("watermark_confidence"),
            "audio_validation": validation,
            "sha256": sha256_file(target),
        })
        raw_path.unlink(missing_ok=True)
        normalized_path.unlink(missing_ok=True)

    for folder in (raw_dir, normalized_dir):
        for path in folder.glob("*"):
            path.unlink(missing_ok=True)
        folder.rmdir()

    write_blind_review(blind_dir, mapping)

    one_shot_rows = [row for row in mapping if row["mode"] == "one_shot"]
    stream_rows = [row for row in mapping if row["mode"] == "streaming"]
    by_case: dict[str, dict[str, Any]] = {}
    for case_name in TEXT_CASES:
        selected = [row for row in one_shot_rows if row["text_case"] == case_name]
        audio_seconds = sum(row["duration_seconds"] for row in selected)
        compute_seconds = sum(row["generation_seconds"] for row in selected)
        by_case[case_name] = {
            "samples": len(selected),
            "audio_seconds": round(audio_seconds, 3),
            "synthesis_seconds": round(compute_seconds, 3),
            "audio_over_compute": round(audio_seconds / max(compute_seconds, 1e-6), 4),
            "compute_over_audio": round(compute_seconds / max(audio_seconds, 1e-6), 4),
            "mean_near_silence_ratio": round(
                sum(row["audio_validation"]["near_silence_ratio"] for row in selected)
                / len(selected),
                5,
            ),
        }

    stream_audio_seconds = sum(row["duration_seconds"] for row in stream_rows)
    stream_ttfa_values = [
        row["time_to_first_audio_seconds"] for row in stream_rows
        if row.get("time_to_first_audio_seconds") is not None
    ]
    report_summary = {
        "benchmark": "VoiceStudio local ZeroTTS Vietnamese CPU screening",
        "status": "technically_validated_not_human_approved",
        "model_id": MODEL_ID,
        "model_revision": revision,
        "package_distribution_version": installed_version,
        "module___version__": package_module_version,
        "package_version_mismatch": installed_version != package_module_version,
        "device": "onnxruntime-cpu",
        "providers": ["CPUExecutionProvider"],
        "threads": THREADS,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "logical_cpu_count": os.cpu_count(),
        "native_sample_rate": SAMPLE_RATE,
        "output_sample_rate": OUTPUT_RATE,
        "output_bits": OUTPUT_BITS,
        "model_load_seconds": round(model_load_seconds, 3),
        "warmup_seconds": round(warmup_seconds, 3),
        "peak_rss_during_tts_mib": peak_rss_during_tts,
        "preset_voice_count": len(EXPECTED_VOICES),
        "preset_voice_ids": list(EXPECTED_VOICES),
        "one_shot_samples": len(one_shot_rows),
        "streaming_samples": len(stream_rows),
        "total_samples": len(mapping),
        "one_shot_total_audio_seconds": round(
            sum(row["duration_seconds"] for row in one_shot_rows), 3
        ),
        "one_shot_total_compute_seconds": round(total_one_shot_seconds, 3),
        "one_shot_audio_over_compute": round(
            sum(row["duration_seconds"] for row in one_shot_rows)
            / max(total_one_shot_seconds, 1e-6),
            4,
        ),
        "stream_total_audio_seconds": round(stream_audio_seconds, 3),
        "stream_total_compute_seconds": round(stream_total_seconds, 3),
        "stream_audio_over_compute": round(
            stream_audio_seconds / max(stream_total_seconds, 1e-6),
            4,
        ),
        "stream_mean_ttfa_seconds": round(
            sum(stream_ttfa_values) / max(len(stream_ttfa_values), 1),
            4,
        ),
        "stream_ttfa_max_seconds": round(max(stream_ttfa_values), 4)
        if stream_ttfa_values else None,
        "per_text_case": by_case,
        "human_review": "not_completed",
        "production_promotion": "blocked_pending_blind_native_vietnamese_review_and_training_data_and_voice_source_rights_review",
        "limitations": [
            "Only eight bundled preset voices were tested; the local voice encoder is not published in this release.",
            "The current release cannot create new voice latents from user-recorded audio locally.",
            "This is a Vietnamese-first model; plain-English voice generation is not claimed or tested.",
            "The official CPU benchmark is maintainer-reported; this VoiceStudio run is the independent GitHub-hosted CPU measurement.",
            "No ASR/WER or MOS score is computed in this run; native Vietnamese human review remains required.",
            "The ZeroBench-TTS dataset is CC-BY-NC-4.0 and is not included in the artifact or used for production training.",
            "MIT model/code licensing does not by itself prove individual training-source recording consent or commercial rights.",
        ],
        "samples": [
            {key: value for key, value in row.items() if key != "raw_path"}
            for row in mapping
        ],
    }
    (analysis_dir / "benchmark.json").write_text(
        json.dumps({"summary": report_summary, "sample_mapping": report_summary["samples"]},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (analysis_dir / "README.md").write_text(
        "Technical mapping only. The blind-review directory contains anonymous WAVs "
        "and an empty score sheet. The current ZeroTTS package includes eight preset "
        "latents but not the reference-audio encoder required to create new voices. "
        "No production identity count or rights approval is claimed.\n",
        encoding="utf-8",
    )

    lines = [
        "# ZeroTTS local CPU benchmark",
        f"- Model revision: {revision}",
        f"- PyPI package: zerotts=={installed_version}",
        f"- Module __version__: {package_module_version}",
        f"- Model load: {model_load_seconds:.2f}s",
        f"- Warmup: {warmup_seconds:.2f}s",
        f"- Peak RSS during TTS: {peak_rss_during_tts if peak_rss_during_tts is not None else 'unavailable'} MiB",
        f"- Bundled presets: {len(EXPECTED_VOICES)}",
        f"- One-shot samples: {len(one_shot_rows)}",
        f"- Streaming samples: {len(stream_rows)}",
        f"- Mean streaming TTFA: {report_summary['stream_mean_ttfa_seconds']:.3f}s",
        f"- One-shot audio/compute: {report_summary['one_shot_audio_over_compute']:.3f}x",
        f"- Streaming audio/compute: {report_summary['stream_audio_over_compute']:.3f}x",
        "",
        "| Vietnamese text case | Samples | Audio (s) | Synthesis (s) | Audio/compute |",
        "|---|---:|---:|---:|---:|",
    ]
    for case_name, stats in by_case.items():
        lines.append(
            f"| {case_name} | {stats['samples']} | {stats['audio_seconds']:.2f} | "
            f"{stats['synthesis_seconds']:.2f} | {stats['audio_over_compute']:.3f}x |"
        )
    lines.extend([
        "",
        "Human listening and source-rights review are incomplete. "
        "This is not a production voice pack.",
    ])
    (output / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report_summary, ensure_ascii=False, indent=2), flush=True)
    return report_summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("dist/zerotts-cpu"))
    args = parser.parse_args()
    if args.check:
        check_contract()
        print("ZeroTTS local CPU benchmark static checks: OK")
        return 0
    run(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
