#!/usr/bin/env python3
"""Internal CPU screen for Vietnamese reference-voice cloning with OmniVoice."""
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
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "k2-fsa/OmniVoice"
TOKENIZER_ID = "eustlb/higgs-audio-v2-tokenizer"
OMNIVOICE_SOURCE_SHA = "08be0b4ccbac3e13e374e86fbfead4b4cac343e2"
KORVATTS_VERSION = "0.1.3"
NUM_STEPS = 32
THREADS = max(1, min(4, os.cpu_count() or 1))
REFERENCE_VOICES = (
    {
        "reference_id": "synthetic_reference_a",
        "korva_voice": "bao_kim",
        "seed": 20261103,
        "text": (
            "Xin chào, tôi đang đọc một đoạn văn ngắn để tạo mẫu tham chiếu "
            "tiếng Việt cho phép thử tổng hợp giọng nói."
        ),
    },
    {
        "reference_id": "synthetic_reference_b",
        "korva_voice": "gia_bao",
        "seed": 20261104,
        "text": (
            "Đây là giọng tham chiếu thứ hai, được tạo hoàn toàn bằng mô hình "
            "tổng hợp để kiểm tra khả năng tái sử dụng danh tính giọng nói."
        ),
    },
)
TARGET_TEXTS = (
    "Hệ thống đã hoàn tất bước kiểm tra đầu tiên. Bây giờ, chúng ta sẽ đánh giá "
    "khả năng phát âm tiếng Việt, nhịp điệu và độ tự nhiên của câu nói.",
    "Ngày 3 tháng 11 năm 2026, nhóm nghiên cứu cập nhật mô hình trên GitHub. "
    "Phiên bản mới hỗ trợ xử lý văn bản, lưu trữ dữ liệu và xuất âm thanh WAV.",
)
KORVA_SAMPLE_RATE = 44_100
OUTPUT_SAMPLE_RATE = 48_000
OUTPUT_BITS = 24


def check_contract() -> None:
    if len(REFERENCE_VOICES) != 2 or len(TARGET_TEXTS) != 2:
        raise ValueError("Expected two synthetic reference identities and two target texts.")
    if NUM_STEPS != 32:
        raise ValueError("The first OmniVoice screen must use its quality-oriented 32-step baseline.")
    if len({item["korva_voice"] for item in REFERENCE_VOICES}) != 2:
        raise ValueError("Synthetic reference sources must be two distinct KorvaTTS presets.")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
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
    spec = importlib.util.spec_from_file_location("omnivoice_internal_voice_builder", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load VoiceStudio audio normalization/watermark helpers.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def materialize_snapshot(snapshot_dir: Path, target_dir: Path) -> None:
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(snapshot_dir, target_dir, symlinks=False)


def write_blind_review(folder: Path, rows: list[dict[str, Any]]) -> None:
    public_rows = [{"blind_id": row["blind_id"], "file_name": row["file_name"]} for row in rows]
    random.Random(20261103).shuffle(public_rows)
    sections = []
    for row in public_rows:
        blind_id = html.escape(row["blind_id"])
        filename = html.escape(row["file_name"])
        sections.append(
            f'<section><h2>{blind_id}</h2><audio controls preload="none" src="{filename}"></audio></section>'
        )
    page = (
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>OmniVoice Vietnamese blind listening review</title>"
        "<style>body{font:16px system-ui;max-width:800px;margin:32px auto;padding:0 18px}"
        "audio{width:100%}section{padding:12px 0;border-bottom:1px solid #ddd}</style>"
        "<h1>Blind Vietnamese voice-cloning review</h1>"
        "<p>These clips are anonymous internal evaluation outputs. Rate identity "
        "consistency, Vietnamese tones, pronunciation, naturalness and prosody.</p>"
        + "".join(sections) + "</html>"
    )
    (folder / "index.html").write_text(page, encoding="utf-8")
    columns = [
        "blind_id",
        "identity_consistency_1_5",
        "naturalness_1_5",
        "tone_accuracy_1_5",
        "pronunciation_1_5",
        "prosody_1_5",
        "notes",
    ]
    with (folder / "human-review.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in public_rows:
            writer.writerow({"blind_id": row["blind_id"], **{key: "" for key in columns[1:]}})


def run(output: Path) -> dict[str, Any]:
    import numpy as np
    import soundfile as sf
    import torch
    from huggingface_hub import HfApi, snapshot_download
    from omnivoice import OmniVoice
    from korvatts import TTS

    check_contract()
    omnivoice_version = importlib.metadata.version("omnivoice")
    korvatts_version = importlib.metadata.version("korvatts")
    if korvatts_version != KORVATTS_VERSION:
        raise RuntimeError(f"Expected korvatts=={KORVATTS_VERSION}, got {korvatts_version}.")
    if torch.cuda.is_initialized():
        raise RuntimeError("Unexpected initialized CUDA context in a CPU-only benchmark.")
    torch.set_num_threads(THREADS)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass

    model_revision = HfApi().model_info(MODEL_ID, files_metadata=False).sha
    tokenizer_revision = HfApi().model_info(TOKENIZER_ID, files_metadata=False).sha
    if not isinstance(model_revision, str) or len(model_revision) != 40:
        raise RuntimeError("Could not resolve an immutable OmniVoice model revision.")
    if not isinstance(tokenizer_revision, str) or len(tokenizer_revision) != 40:
        raise RuntimeError("Could not resolve an immutable audio-tokenizer revision.")

    hf_cache = Path(os.environ.get("HF_HOME", "/tmp/omnivoice-hf-home"))
    model_snapshot = Path(snapshot_download(
        repo_id=MODEL_ID,
        revision=model_revision,
        cache_dir=str(hf_cache),
    ))
    tokenizer_snapshot = Path(snapshot_download(
        repo_id=TOKENIZER_ID,
        revision=tokenizer_revision,
        cache_dir=str(hf_cache),
    ))
    local_model = Path("/tmp/omnivoice-local-model")
    print(f"[OmniVoice] Materialize model snapshot {model_revision}", flush=True)
    materialize_snapshot(model_snapshot, local_model)
    materialize_snapshot(tokenizer_snapshot, local_model / "audio_tokenizer")
    model_bytes = sum(p.stat().st_size for p in local_model.rglob("*") if p.is_file())

    # Reference clips are synthetic KorvaTTS outputs. They test the local
    # reference-audio clone path; they are not real people or production assets.
    reference_dir = Path("/tmp/omnivoice-synthetic-references")
    reference_dir.mkdir(parents=True, exist_ok=True)
    korva_revision = HfApi().model_info("dogenthq/KorvaTTS", files_metadata=False).sha
    if not isinstance(korva_revision, str) or len(korva_revision) != 40:
        raise RuntimeError("Could not resolve an immutable KorvaTTS reference-model revision.")
    print(
        f"[OmniVoice] Generate two local synthetic Vietnamese references "
        f"with KorvaTTS@{korva_revision}",
        flush=True,
    )
    korva_assets = Path(snapshot_download(
        repo_id="dogenthq/KorvaTTS",
        revision=korva_revision,
        allow_patterns=["onnx/*", "voice_styles/*"],
        cache_dir=str(hf_cache),
    ))
    korva = TTS(
        assets_dir=str(korva_assets),
        device="cpu",
        auto_download=False,
        num_threads=THREADS,
    )
    refs: list[dict[str, Any]] = []
    ref_generation_total = 0.0
    prompt_encode_total = 0.0
    prompts: dict[str, Any] = {}

    for spec in REFERENCE_VOICES:
        np.random.seed(int(spec["seed"]))
        started = time.perf_counter()
        waveform, reported_duration = korva.synthesize(
            text=spec["text"],
            voice=spec["korva_voice"],
            lang="vi",
            total_steps=32,
            speed=1.0,
            seed=int(spec["seed"]),
        )
        elapsed = time.perf_counter() - started
        ref_generation_total += elapsed
        audio = np.asarray(waveform, dtype=np.float32).squeeze()
        if audio.ndim != 1 or audio.size == 0 or not np.isfinite(audio).all():
            raise RuntimeError(f"{spec['reference_id']}: invalid KorvaTTS reference waveform.")
        duration = len(audio) / KORVA_SAMPLE_RATE
        if duration < 3.0 or duration > 20.0:
            raise RuntimeError(f"{spec['reference_id']}: invalid reference duration {duration:.2f}s.")
        reference_path = reference_dir / f"{spec['reference_id']}.wav"
        sf.write(reference_path, audio, KORVA_SAMPLE_RATE, subtype="PCM_16")
        refs.append({
            "reference_id": spec["reference_id"],
            "source_family": "KorvaTTS synthetic preset",
            "source_style": spec["korva_voice"],
            "reference_text": spec["text"],
            "source_duration_seconds": round(duration, 3),
            "reported_duration_seconds": round(float(reported_duration), 3),
            "korva_generation_seconds": round(elapsed, 3),
            "file_path": str(reference_path),
        })
        print(
            f"[OmniVoice] Reference {spec['reference_id']} ready: "
            f"{duration:.2f}s; local KorvaTTS compute {elapsed:.2f}s",
            flush=True,
        )
        prompt_start = time.perf_counter()
        prompts[spec["reference_id"]] = model.create_voice_clone_prompt(
            ref_audio=str(reference_path),
            ref_text=spec["text"],
            preprocess_prompt=True,
        )
        prompt_seconds = time.perf_counter() - prompt_start
        prompt_encode_total += prompt_seconds
        refs[-1]["prompt_encode_seconds"] = round(prompt_seconds, 3)
        print(
            f"[OmniVoice] Encoded reusable prompt {spec['reference_id']} in {prompt_seconds:.2f}s",
            flush=True,
        )

    del korva
    gc.collect()

    print(
        f"[OmniVoice] Loading {MODEL_ID}@{model_revision} on CPU; "
        f"tokenizer={TOKENIZER_ID}@{tokenizer_revision}; threads={THREADS}",
        flush=True,
    )
    load_started = time.perf_counter()
    model = OmniVoice.from_pretrained(
        str(local_model),
        device_map="cpu",
        dtype=torch.float32,
        attn_implementation="sdpa",
        low_cpu_mem_usage=True,
        load_asr=False,
    )
    model_load_seconds = time.perf_counter() - load_started
    if str(model.device) != "cpu":
        raise RuntimeError(f"Expected OmniVoice on CPU, got {model.device}.")
    supported_languages = {str(x).lower() for x in model.supported_language_ids()}
    if "vi" not in supported_languages:
        raise RuntimeError("OmniVoice checkpoint does not report Vietnamese (vi) support.")
    native_sample_rate = int(model.sampling_rate)
    print(
        f"[OmniVoice] Model loaded in {model_load_seconds:.2f}s; "
        f"sample_rate={native_sample_rate}; model_snapshot={model_bytes / (1024**3):.2f} GiB",
        flush=True,
    )

    output.mkdir(parents=True, exist_ok=True)
    blind_dir = output / "blind-review"
    analysis_dir = output / "analysis"
    work_dir = Path("/tmp/omnivoice-output-work")
    for folder in (blind_dir, analysis_dir, work_dir):
        folder.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    total_generation_seconds = 0.0
    for ref_index, reference in enumerate(refs):
        for target_index, target_text in enumerate(TARGET_TEXTS):
            blind_id = f"clone_{len(rows) + 1:02d}"
            seed = 20261110 + ref_index * 100 + target_index
            torch.manual_seed(seed)
            np.random.seed(seed)
            started = time.perf_counter()
            generated = model.generate(
                text=target_text,
                language="vi",
                voice_clone_prompt=prompts[reference["reference_id"]],
                num_step=NUM_STEPS,
                guidance_scale=2.0,
                postprocess_output=True,
            )
            elapsed = time.perf_counter() - started
            total_generation_seconds += elapsed
            if not isinstance(generated, list) or len(generated) != 1:
                raise RuntimeError(f"{blind_id}: expected a single generated audio array.")
            waveform = np.asarray(generated[0], dtype=np.float32).squeeze()
            if waveform.ndim != 1 or waveform.size == 0 or not np.isfinite(waveform).all():
                raise RuntimeError(f"{blind_id}: invalid OmniVoice waveform.")
            duration = len(waveform) / native_sample_rate
            if not 1.0 <= duration <= 120.0:
                raise RuntimeError(f"{blind_id}: implausible output duration {duration:.2f}s.")
            raw_path = work_dir / f"{blind_id}.wav"
            sf.write(raw_path, waveform, native_sample_rate, subtype="PCM_16")
            rows.append({
                "blind_id": blind_id,
                "reference_id": reference["reference_id"],
                "reference_style": reference["source_style"],
                "target_text": target_text,
                "seed": seed,
                "num_step": NUM_STEPS,
                "duration_seconds": round(duration, 3),
                "generation_seconds": round(elapsed, 3),
                "audio_over_compute": round(duration / max(elapsed, 1e-6), 4),
                "compute_over_audio": round(elapsed / max(duration, 1e-6), 4),
                "raw_path": str(raw_path),
            })
            print(
                f"[OmniVoice] {blind_id} ref={reference['reference_id']}: "
                f"{duration:.2f}s audio / {elapsed:.2f}s compute; "
                f"audio/compute={duration / max(elapsed, 1e-6):.3f}x",
                flush=True,
            )

    peak_rss_tts = peak_rss_mib()
    del model
    del prompts
    gc.collect()

    # Import provenance helpers only after the TTS peak-RSS snapshot.
    builder = load_builder()
    for row in rows:
        raw_path = Path(row["raw_path"])
        normalized_path = work_dir / f"{row['blind_id']}.normalized.wav"
        target_path = blind_dir / f"{row['blind_id']}.wav"
        builder.run_ffmpeg_normalize(raw_path, normalized_path, OUTPUT_SAMPLE_RATE, OUTPUT_BITS)
        watermark = builder.watermark_and_verify(
            normalized_path,
            OUTPUT_BITS,
            context=f"omnivoice.internal.vi-clone.{row['blind_id']}",
        )
        validation = builder.validate_audio(normalized_path, OUTPUT_SAMPLE_RATE, OUTPUT_BITS)
        shutil.copy2(normalized_path, target_path)
        row.update({
            "file_name": target_path.name,
            "output_sample_rate": OUTPUT_SAMPLE_RATE,
            "output_bits": OUTPUT_BITS,
            "watermark": "verified",
            "watermark_confidence": watermark.get("watermark_confidence"),
            "audio_validation": validation,
            "sha256": sha256_file(target_path),
        })
        raw_path.unlink(missing_ok=True)
        normalized_path.unlink(missing_ok=True)

    for path in reference_dir.glob("*"):
        path.unlink(missing_ok=True)
    reference_dir.rmdir()
    work_dir.rmdir()

    # Shuffle IDs independently of generation order so repeated outputs from
    # the same synthetic reference cannot be inferred from adjacent filenames.
    review_rng = random.Random(20261103)
    review_rng.shuffle(rows)
    for index, row in enumerate(rows, start=1):
        source_path = blind_dir / row["file_name"]
        new_id = f"sample_{index:02d}"
        target_path = blind_dir / f"{new_id}.wav"
        source_path.rename(target_path)
        row["blind_id"] = new_id
        row["file_name"] = target_path.name
        row["sha256"] = sha256_file(target_path)
    write_blind_review(blind_dir, rows)
    generated_audio_seconds = sum(row["duration_seconds"] for row in rows)
    summary = {
        "benchmark": "VoiceStudio internal OmniVoice Vietnamese reference-cloning CPU screen",
        "status": "technically_validated_not_human_approved",
        "upstream_source_repo": "https://github.com/k2-fsa/OmniVoice",
        "upstream_source_commit": OMNIVOICE_SOURCE_SHA,
        "upstream_source_license": "Apache-2.0",
        "model_id": MODEL_ID,
        "model_revision": model_revision,
        "model_weight_license": "not_declared_in_current_hugging_face_repo_metadata",
        "audio_tokenizer_id": TOKENIZER_ID,
        "audio_tokenizer_revision": tokenizer_revision,
        "audio_tokenizer_weight_license": "not_confirmed_in_current_hugging_face_repo_metadata",
        "omnivoice_package_version": omnivoice_version,
        "korvatts_package_version": korvatts_version,
        "korvatts_reference_model_revision": korva_revision,
        "device": "cpu",
        "dtype": "float32",
        "attention_implementation": "sdpa",
        "threads": THREADS,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "logical_cpu_count": os.cpu_count(),
        "model_snapshot_bytes_including_audio_tokenizer": model_bytes,
        "native_sample_rate": native_sample_rate,
        "output_sample_rate": OUTPUT_SAMPLE_RATE,
        "output_bits": OUTPUT_BITS,
        "model_load_seconds": round(model_load_seconds, 3),
        "reference_voice_count": len(refs),
        "synthetic_reference_generation_seconds": round(ref_generation_total, 3),
        "clone_prompt_encode_seconds_total": round(prompt_encode_total, 3),
        "num_steps": NUM_STEPS,
        "generated_samples": len(rows),
        "generated_audio_seconds": round(generated_audio_seconds, 3),
        "synthesis_compute_seconds": round(total_generation_seconds, 3),
        "audio_over_compute": round(generated_audio_seconds / max(total_generation_seconds, 1e-6), 4),
        "compute_over_audio": round(total_generation_seconds / max(generated_audio_seconds, 1e-6), 4),
        "peak_rss_across_cpu_pipeline_mib": peak_rss_tts,
        "human_review": "not_completed",
        "production_promotion": "blocked_pending_contributor_consent_weight_license_review_and_blind_native_vietnamese_listening",
        "important_boundaries": [
            "Both reference clips are synthetic KorvaTTS preset outputs, not human recordings.",
            "This test screens the local prompt/clone pipeline only; it does not count outputs as new production speaker identities.",
            "Real contributor cloning requires explicit consent for the reference recording, synthesis, distribution and any commercial use.",
            "The upstream source-code repository is Apache-2.0, but the current Hugging Face model-weight and tokenizer-weight metadata do not declare a license; do not redistribute or commercially promote their weights/outputs until clarified.",
            "Voice design via text instruction is trained primarily on English and Chinese; this benchmark uses Vietnamese reference-audio cloning instead.",
            "No hosted TTS endpoints or paid providers are used.",
        ],
        "synthetic_references": [
            {key: value for key, value in item.items() if key != "file_path"}
            for item in refs
        ],
        "samples": [
            {key: value for key, value in row.items() if key != "raw_path"}
            for row in rows
        ],
    }
    (analysis_dir / "benchmark.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (analysis_dir / "README.md").write_text(
        "Internal evaluation only. The two reference clips were generated with "
        "KorvaTTS presets and were deleted after prompt encoding. No human speaker "
        "recordings, consented contributor assets, model weights or prompt mapping "
        "are included in the blind-review artifact.\n",
        encoding="utf-8",
    )
    lines = [
        "# OmniVoice Vietnamese CPU clone screen",
        f"- Upstream source commit: {OMNIVOICE_SOURCE_SHA}",
        f"- Model revision: {model_revision}",
        f"- Audio tokenizer revision: {tokenizer_revision}",
        f"- Source repository license: Apache-2.0",
        "- Model weights license: not declared in current HF model metadata",
        "- Audio tokenizer weights license: not confirmed",
        "- Device/dtype: CPU / float32 / SDPA",
        f"- Model load: {model_load_seconds:.2f}s",
        f"- Model snapshot including audio tokenizer: {model_bytes / (1024**3):.2f} GiB",
        f"- Peak RSS across CPU pipeline: {peak_rss_tts if peak_rss_tts is not None else 'unavailable'} MiB",
        f"- Prompt encoding total: {prompt_encode_total:.2f}s",
        f"- Samples: {len(rows)}",
        f"- Output audio: {generated_audio_seconds:.2f}s",
        f"- Synthesis compute: {total_generation_seconds:.2f}s",
        f"- Audio / compute: {summary['audio_over_compute']:.3f}x",
        f"- Compute / audio: {summary['compute_over_audio']:.3f}x",
        "",
        "Both references are synthetic KorvaTTS preset outputs, not real people.",
        "No contributor approval or production rights are asserted.",
        "Human listening and checkpoint-weight license review remain incomplete.",
    ]
    (output / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("dist/omnivoice-internal"))
    args = parser.parse_args()
    if args.check:
        check_contract()
        print("OmniVoice local Vietnamese clone-screen static checks: OK")
        return 0
    run(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
