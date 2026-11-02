#!/usr/bin/env python3
"""Research-only test of interpolated KorvaTTS speaker-style tensors."""
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
VOICE_PAIRS = (
    ("bao_kim", "khanh_vy"),
    ("ngoc_huyen", "phuong_linh"),
    ("quynh_nhu", "bao_kim"),
    ("gia_bao", "hoang_nam"),
    ("huu_dat", "quang_huy"),
)
WEIGHTS_B = (0.25, 0.5, 0.75)
VI_TEXT = (
    "Chào bạn, hôm nay chúng ta sẽ cùng khám phá một câu chuyện mới. "
    "Hãy lắng nghe thật rõ từng chi tiết nhé."
)
SAMPLE_RATE = 44_100
OUTPUT_RATE = 48_000
OUTPUT_BITS = 24
TOTAL_STEPS = 32
SPEED = 1.05


def check_contract() -> None:
    names = [name for pair in VOICE_PAIRS for name in pair]
    allowed = {
        "bao_kim", "gia_bao", "hoang_nam", "huu_dat", "khanh_vy",
        "ngoc_huyen", "phuong_linh", "quynh_nhu", "quang_huy", "thanh_phong",
    }
    if len(VOICE_PAIRS) != 5 or not set(names) <= allowed:
        raise ValueError("Interpolation pairs must use the ten published KorvaTTS presets.")
    if len(WEIGHTS_B) != 3 or any(not 0.0 < weight < 1.0 for weight in WEIGHTS_B):
        raise ValueError("Interpolation weights must be strictly between zero and one.")
    if not VI_TEXT.strip():
        raise ValueError("Vietnamese benchmark text must be non-empty.")


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
    spec = importlib.util.spec_from_file_location("voice_library_builder_for_style_mix", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load VoiceStudio's audio normalization/watermark helpers.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def flat_style(style: Any) -> Any:
    import numpy as np
    return np.concatenate((
        np.asarray(style.ttl, dtype=np.float64).ravel(),
        np.asarray(style.dp, dtype=np.float64).ravel(),
    ))


def cosine_similarity(a: Any, b: Any) -> float:
    import numpy as np
    left, right = flat_style(a), flat_style(b)
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom <= 1e-12:
        raise ValueError("A speaker-style embedding has effectively zero norm.")
    return float(np.dot(left, right) / denom)


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
        "<title>Blind KorvaTTS style interpolation review</title>"
        "<style>body{font:16px system-ui;max-width:760px;margin:32px auto;padding:0 18px}"
        "audio{width:100%}section{padding:16px 0;border-bottom:1px solid #ddd}</style>"
        "<h1>Anonymous Vietnamese style-mix listening review</h1>"
        "<p>Samples are blind. They are interpolated preset styles, not verified independent speaker identities.</p>"
        + "".join(sections) + "</html>"
    )
    (folder / "index.html").write_text(page, encoding="utf-8")
    columns = [
        "blind_id", "naturalness_1_5", "pronunciation_1_5",
        "prosody_1_5", "distinctness_1_5", "notes",
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
    from korvatts import TTS, VoiceStyle

    check_contract()
    version = importlib.metadata.version("korvatts")
    if version != PACKAGE_VERSION:
        raise RuntimeError(f"Expected korvatts=={PACKAGE_VERSION}, got {version}")
    revision = HfApi().model_info(MODEL_ID, files_metadata=False).sha
    if not isinstance(revision, str) or len(revision) != 40:
        raise RuntimeError("Could not pin KorvaTTS to an immutable 40-character revision.")
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

    started = time.perf_counter()
    tts = TTS(
        assets_dir=assets, device="cpu", auto_download=False,
        num_threads=max(1, min(4, os.cpu_count() or 1)),
    )
    model_load_seconds = time.perf_counter() - started
    available = set(tts.list_voices())
    expected = {name for pair in VOICE_PAIRS for name in pair}
    if not expected <= available:
        raise RuntimeError(f"Required source presets are missing: {sorted(expected - available)}")
    if int(tts.sample_rate) != SAMPLE_RATE:
        raise RuntimeError(f"Expected native 44.1kHz output, got {tts.sample_rate}")

    helper = load_builder()
    sources = {name: tts.get_voice(name) for name in sorted(expected)}
    rows: list[dict[str, Any]] = []
    mappings: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    total_compute = 0.0

    def render_candidate(
        candidate_name: str,
        style: Any,
        source_a: str,
        source_b: str,
        weight_b: float,
    ) -> None:
        nonlocal total_compute
        blind_id = f"blend_{len(rows) + len(failures) + 1:02d}"
        raw = raw_dir / f"{blind_id}.wav"
        normalized = normalized_dir / f"{blind_id}.wav"
        t0 = time.perf_counter()
        waveform, duration_reported = tts.synthesize(
            text=VI_TEXT, voice=style, lang="vi",
            total_steps=TOTAL_STEPS, speed=SPEED,
            seed=20261102 + len(rows) + len(failures),
        )
        elapsed = time.perf_counter() - t0
        total_compute += elapsed
        audio = np.asarray(waveform, dtype=np.float32).squeeze()
        if audio.ndim != 1 or audio.size == 0 or not np.isfinite(audio).all():
            raise RuntimeError(f"{blind_id}: invalid synthesized waveform.")
        sf.write(str(raw), audio, SAMPLE_RATE, format="WAV", subtype="FLOAT")
        duration = len(audio) / SAMPLE_RATE
        if not 2.0 <= duration <= 60.0:
            raise RuntimeError(f"{blind_id}: implausible duration {duration:.2f}s.")
        helper.run_ffmpeg_normalize(raw, normalized, OUTPUT_RATE, OUTPUT_BITS)
        watermark = helper.watermark_and_verify(
            normalized, OUTPUT_BITS, context=f"korvatts.style-mix.{blind_id}"
        )
        checks = helper.validate_audio(normalized, OUTPUT_RATE, OUTPUT_BITS)
        target = blind_dir / f"{blind_id}.wav"
        shutil.copy2(normalized, target)
        row = {
            "blind_id": blind_id,
            "file_name": target.name,
            "duration_seconds": round(duration, 3),
            "reported_duration_seconds": round(float(duration_reported), 3),
            "generation_seconds": round(elapsed, 3),
            "rtfx": round(duration / max(elapsed, 1e-6), 4),
            "watermark": "verified",
            "watermark_confidence": watermark.get("watermark_confidence"),
            "audio_validation": checks,
            "sha256": sha256(target),
        }
        rows.append(row)
        mappings.append({
            **row,
            "candidate_name": candidate_name,
            "source_voice_a": source_a,
            "source_voice_b": source_b,
            "weight_b": weight_b,
            "weight_a": 1.0 - weight_b,
            "style_embedding_cosine_to_a": cosine_similarity(style, sources[source_a]),
            "style_embedding_cosine_to_b": cosine_similarity(style, sources[source_b]),
            "native_sample_rate": SAMPLE_RATE,
            "output_sample_rate": OUTPUT_RATE,
            "output_bits": OUTPUT_BITS,
            "text": VI_TEXT,
        })
        print(
            f"[style-mix] {blind_id} {candidate_name}: {duration:.2f}s / {elapsed:.2f}s; "
            f"RTFx={row['rtfx']:.3f}; source similarities="
            f"{mappings[-1]['style_embedding_cosine_to_a']:.4f},"
            f"{mappings[-1]['style_embedding_cosine_to_b']:.4f}",
            flush=True,
        )
        raw.unlink(missing_ok=True)
        normalized.unlink(missing_ok=True)

    for name_a, name_b in VOICE_PAIRS:
        style_a, style_b = sources[name_a], sources[name_b]
        if style_a.ttl.shape != style_b.ttl.shape or style_a.dp.shape != style_b.dp.shape:
            raise RuntimeError(f"Incompatible style tensor shapes: {name_a}, {name_b}")
        for weight_b in WEIGHTS_B:
            candidate_name = f"mix-{name_a}-{name_b}-{int(weight_b * 100):02d}"
            ttl = np.asarray(
                style_a.ttl * (1.0 - weight_b) + style_b.ttl * weight_b,
                dtype=np.float32,
            )
            dp = np.asarray(
                style_a.dp * (1.0 - weight_b) + style_b.dp * weight_b,
                dtype=np.float32,
            )
            if not np.isfinite(ttl).all() or not np.isfinite(dp).all():
                raise RuntimeError(f"{candidate_name}: embedding interpolation is not finite.")
            candidate = VoiceStyle(ttl=ttl, dp=dp, name=candidate_name)
            sim_a = cosine_similarity(candidate, style_a)
            sim_b = cosine_similarity(candidate, style_b)
            if max(sim_a, sim_b) >= 0.999999:
                failures.append({
                    "candidate": candidate_name,
                    "reason": "interpolated embedding collapsed to an endpoint",
                })
                continue
            try:
                render_candidate(candidate_name, candidate, name_a, name_b, weight_b)
            except Exception as exc:
                failures.append({
                    "candidate": candidate_name,
                    "reason": f"{type(exc).__name__}: {str(exc)[:400]}",
                })
                print(f"[style-mix] REJECT {candidate_name}: {type(exc).__name__}: {exc}", flush=True)

    peak = peak_rss_mib()
    del tts
    gc.collect()
    write_review(blind_dir, rows)
    for folder in (raw_dir, normalized_dir):
        for path in folder.glob("*"):
            path.unlink(missing_ok=True)
        folder.rmdir()

    summary = {
        "benchmark": "KorvaTTS interpolated speaker-style CPU feasibility",
        "status": "technically_validated_not_human_approved",
        "model_id": MODEL_ID,
        "model_revision": revision,
        "package_version": version,
        "device": "onnx-cpu",
        "model_load_seconds": round(model_load_seconds, 3),
        "peak_rss_mib": peak,
        "source_preset_count": len(available),
        "pair_count": len(VOICE_PAIRS),
        "weights_b": list(WEIGHTS_B),
        "planned_blend_candidates": len(VOICE_PAIRS) * len(WEIGHTS_B),
        "generated_blend_samples": len(rows),
        "failed_or_collapsed_candidates": failures,
        "total_audio_seconds": round(sum(row["duration_seconds"] for row in rows), 3),
        "total_synthesis_seconds": round(total_compute, 3),
        "overall_rtfx": round(
            sum(row["duration_seconds"] for row in rows) / max(total_compute, 1e-6), 4
        ),
        "human_review": "not_completed",
        "production_promotion": "blocked_pending_human_listening_and_training_data_and_voice_source_rights_review",
        "identity_claim": "none; blended embeddings are experimental timbre variants, not verified independent speaker identities",
        "limitations": [
            "Interpolation can produce hybrid, ambiguous, or unnatural timbres despite valid waveforms.",
            "Embedding cosine similarity is not speaker verification or evidence of human-perceived distinctness.",
            "Ten fixed preset embeddings provide limited coverage of the speaker-style space.",
            "No new human contributors or consented recordings are introduced by this experiment.",
            "The upstream training data includes a filtered PhoAudiobook subset; rights review remains required.",
            "Signal checks and AudioSeal do not measure pronunciation, naturalness, accent, or listener preference.",
        ],
    }
    report = {"summary": summary, "sample_mapping": mappings}
    (analysis_dir / "benchmark.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (analysis_dir / "README.md").write_text(
        "Mappings disclose source presets and interpolation weights for researchers. "
        "The blind-review folder deliberately withholds this mapping. No blended style "
        "is approved as a production identity without listener and rights review.\n",
        encoding="utf-8",
    )
    lines = [
        "# KorvaTTS style interpolation experiment",
        f"- Model revision: {revision}",
        f"- Model load: {model_load_seconds:.2f}s",
        f"- Peak RSS: {peak if peak is not None else 'unavailable'} MiB",
        f"- Planned blend candidates: {summary['planned_blend_candidates']}",
        f"- Generated samples: {len(rows)}",
        f"- Failed/collapsed candidates: {len(failures)}",
        f"- Total audio: {summary['total_audio_seconds']:.2f}s",
        f"- Compute: {total_compute:.2f}s",
        f"- Overall RTFx: {summary['overall_rtfx']:.3f}",
        "",
        "| Blind ID | Audio (s) | Compute (s) | RTFx |",
        "|---|---:|---:|---:|",
    ]
    lines.extend(
        f"| {row['blind_id']} | {row['duration_seconds']:.2f} | "
        f"{row['generation_seconds']:.2f} | {row['rtfx']:.3f} |"
        for row in rows
    )
    lines.extend([
        "",
        "No independent speaker identities are claimed. Human listening and rights review are required.",
    ])
    (output / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("dist/korvatts-style-mix"))
    args = parser.parse_args()
    if args.check:
        check_contract()
        print("KorvaTTS style interpolation static check: OK")
        return 0
    run(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
