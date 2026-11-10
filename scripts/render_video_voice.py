#!/usr/bin/env python3
"""Render a video narration job on a GitHub Actions runner.

The public interface is a validated JSON payload in VOICE_JOB_JSON. Inference,
48 kHz mastering, captions, provenance watermarking and packaging stay on the
Actions runner. The output is an NLE-ready WAV plus SRT/VTT and timing metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

SCHEMA_PATH = ROOT / "voice-library" / "video-job.schema.json"
SAMPLE_RATE = 48_000
BITS = 24
TARGET_LUFS = -18.0
TRUE_PEAK_DBTP = -1.5
LRA = 7
MAX_TOTAL_CHARS = 30_000
MAX_RENDERED_CHUNKS = 180
MAX_CHUNK_CHARS = 360
MAX_DURATION_SECONDS = 2 * 60 * 60
DEFAULT_PAUSE_MS = 220
INTERNAL_PAUSE_MS = 140


def log(message: str) -> None:
    print(f"[video-voice] {message}", flush=True)


def load_builder():
    path = ROOT / "scripts" / "build_voice_library.py"
    spec = importlib.util.spec_from_file_location("voice_library_builder", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the pinned voice model adapters")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_job_payload(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("The job payload must be a JSON object")
    import jsonschema

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
    if payload["engine"] in {"piper", "kokoro"} and payload["language"] != "en":
        raise ValueError(f"{payload['engine']} is only supported for English narration jobs")
    total_chars = sum(len(segment["text"].strip()) for segment in payload["segments"])
    if total_chars > MAX_TOTAL_CHARS:
        raise ValueError(f"Narration is too long ({total_chars} characters; limit {MAX_TOTAL_CHARS})")
    if any(not segment["text"].strip() for segment in payload["segments"]):
        raise ValueError("Every narration segment must contain non-whitespace text")
    if len({segment["id"] for segment in payload["segments"]}) != len(payload["segments"]):
        raise ValueError("Narration segment IDs must be unique")
    plan_rendered_chunks(payload["segments"])
    return payload


def split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Pack complete short sentences together; split only when a chunk would exceed the cap."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    text = text.replace("\\r\\n", "\\n").replace("\\r", "\\n").strip()
    if not text:
        return []
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?\\u3002\\uff01\\uff1f])\\s+|\\n+", text)
        if part.strip()
    ]
    chunks: list[str] = []
    pending = ""

    for sentence in sentences:
        if len(sentence) <= max_chars:
            candidate = f"{pending} {sentence}".strip() if pending else sentence
            if len(candidate) <= max_chars:
                pending = candidate
            else:
                if pending:
                    chunks.append(pending)
                pending = sentence
            continue

        if pending:
            chunks.append(pending)
            pending = ""

        remaining = sentence
        while len(remaining) > max_chars:
            cut = remaining.rfind(" ", 0, max_chars + 1)
            if cut < max(40, max_chars // 2):
                cut = max_chars
            chunks.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
        pending = remaining

    if pending:
        chunks.append(pending)
    if not chunks or any(not chunk for chunk in chunks):
        raise ValueError("Text splitter produced no usable speech content")
    return chunks


def plan_rendered_chunks(segment_sources: list[dict]) -> list[dict]:
    """Build the bounded TTS plan once so validation and synthesis use identical chunking."""
    planned: list[dict] = []
    for segment in segment_sources:
        chunks = split_text(segment["text"])
        for chunk_index, chunk in enumerate(chunks):
            planned.append({
                "source_id": segment["id"],
                "chunk_index": chunk_index + 1,
                "chunk_count": len(chunks),
                "text": chunk,
                "pause_ms_after": (
                    int(segment.get("pause_ms_after", DEFAULT_PAUSE_MS))
                    if chunk_index == len(chunks) - 1
                    else INTERNAL_PAUSE_MS
                ),
            })
            if len(planned) > MAX_RENDERED_CHUNKS:
                raise ValueError(
                    f"Narration exceeds the {MAX_RENDERED_CHUNKS}-chunk safety limit "
                    "after sentence packing"
                )
    return planned

def format_timestamp(seconds: float, *, vtt: bool = False) -> str:
    total_ms = max(0, int(round(float(seconds) * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    separator = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def safe_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
    return (slug[:64].strip("-") or "narration")


def write_captions(rows: list[dict], output: Path) -> None:
    srt: list[str] = []
    vtt: list[str] = ["WEBVTT", ""]
    for index, row in enumerate(rows, 1):
        start = format_timestamp(row["start_seconds"])
        end = format_timestamp(row["end_seconds"])
        srt.extend([str(index), f"{start} --> {end}", row["text"], ""])
        vtt.extend([
            f"{format_timestamp(row['start_seconds'], vtt=True)} --> "
            f"{format_timestamp(row['end_seconds'], vtt=True)}",
            row["text"].replace("-->", "—>"),
            "",
        ])
    (output / "captions.srt").write_text("\n".join(srt), encoding="utf-8")
    (output / "captions.vtt").write_text("\n".join(vtt), encoding="utf-8")
    (output / "transcript.txt").write_text(
        "\n\n".join(row["text"] for row in rows) + "\n", encoding="utf-8"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def run_ffmpeg(command: list[str], *, timeout: int = 900) -> None:
    try:
        result = subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc))[-4000:]
        raise RuntimeError(f"FFmpeg failed: {detail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"FFmpeg exceeded its {timeout}s time limit") from exc


def normalize_master(source: Path, target: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required to master the narration")
    run_ffmpeg([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source),
        "-af", f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK_DBTP}:LRA={LRA}",
        "-ar", str(SAMPLE_RATE), "-ac", "1",
        "-c:a", "pcm_s24le", "-map_metadata", "-1",
        str(target),
    ], timeout=1800)

def resample_video_part(source: Path, target: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required on the Actions runner")
    run_ffmpeg([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source),
        "-ar", str(SAMPLE_RATE), "-ac", "1",
        "-c:a", "pcm_s24le", "-map_metadata", "-1",
        str(target),
    ])


def stream_watermark_and_verify(source: Path, destination: Path, context: str) -> dict:
    """Watermark and re-detect in <=30-second blocks to bound runner memory."""
    import numpy as np
    import soundfile as sf
    import torch
    from services.watermark import detect_watermark, mark_synthetic

    info = sf.info(str(source))
    if info.samplerate != SAMPLE_RATE or info.channels != 1 or info.subtype != "PCM_24":
        raise RuntimeError("Pre-mastered narration must be mono 48 kHz PCM-24")
    block_frames = 30 * SAMPLE_RATE
    temporary = destination.with_name(destination.stem + ".watermarked.tmp.wav")
    destination.parent.mkdir(parents=True, exist_ok=True)

    with sf.SoundFile(str(source), mode="r") as reader, sf.SoundFile(
        str(temporary), mode="w", samplerate=SAMPLE_RATE, channels=1, subtype="PCM_24"
    ) as writer:
        remaining = int(info.frames)
        block_index = 0
        while remaining:
            frames = min(block_frames, remaining)
            if remaining > block_frames and remaining - frames < SAMPLE_RATE:
                frames = remaining
            block = reader.read(frames, dtype="float32", always_2d=True)
            if not np.isfinite(block).all():
                raise RuntimeError("Non-finite samples found before watermarking")
            waveform = torch.from_numpy(block.T.copy()).to(torch.float32)
            marked = mark_synthetic(
                waveform, SAMPLE_RATE, context=f"{context}.block-{block_index:04d}", force=True
            )
            writer.write(marked.squeeze(0).detach().cpu().numpy())
            remaining -= len(block)
            block_index += 1
    if not temporary.is_file() or temporary.stat().st_size < 4096:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("Watermarking produced an empty audio file")
    os.replace(temporary, destination)

    # Detect every persisted block, not just the in-memory tensor or first seconds.
    verdicts: list[dict] = []
    with sf.SoundFile(str(destination), mode="r") as reader:
        remaining = int(reader.frames)
        block_index = 0
        while remaining:
            frames = min(block_frames, remaining)
            if remaining > block_frames and remaining - frames < SAMPLE_RATE:
                frames = remaining
            block = reader.read(frames, dtype="float32", always_2d=True)
            waveform = torch.from_numpy(block.T.copy()).to(torch.float32)
            verdict = detect_watermark(waveform, SAMPLE_RATE)
            if not verdict.get("is_watermarked") or not verdict.get("is_omnivoice"):
                raise RuntimeError(
                    "Persisted video narration failed AudioSeal verification "
                    f"at block {block_index}: confidence={verdict.get('confidence')}, "
                    f"error={verdict.get('error')}"
                )
            verdicts.append(verdict)
            remaining -= len(block)
            block_index += 1

    return {
        "status": "verified",
        "block_count": len(verdicts),
        "minimum_confidence": min(float(item.get("confidence", 0)) for item in verdicts),
        "mean_confidence": round(
            sum(float(item.get("confidence", 0)) for item in verdicts) / len(verdicts), 4
        ),
        "message_bits": verdicts[0].get("message_bits", ""),
    }


def validate_final_audio(path: Path) -> dict:
    import numpy as np
    import soundfile as sf

    info = sf.info(str(path))
    if info.format not in {"WAV", "WAVEX"}:
        raise RuntimeError(f"Expected WAV output, got {info.format}")
    if info.subtype != "PCM_24" or info.samplerate != SAMPLE_RATE or info.channels != 1:
        raise RuntimeError(
            f"Expected mono 48 kHz PCM-24; got {info.channels}ch/{info.samplerate}Hz/{info.subtype}"
        )
    if not 1.0 <= info.duration <= MAX_DURATION_SECONDS:
        raise RuntimeError(f"Final duration is outside 1s–{MAX_DURATION_SECONDS}s")
    peak = 0.0
    sum_squares = 0.0
    sample_count = 0
    clipped_count = 0
    with sf.SoundFile(str(path), mode="r") as reader:
        while True:
            block = reader.read(30 * SAMPLE_RATE, dtype="float32", always_2d=True)
            if not len(block):
                break
            if not np.isfinite(block).all():
                raise RuntimeError("Final narration contains NaN or infinite samples")
            absolute = np.abs(block)
            peak = max(peak, float(absolute.max(initial=0.0)))
            sum_squares += float(np.square(block, dtype=np.float64).sum())
            sample_count += int(block.size)
            clipped_count += int(np.count_nonzero(absolute >= 0.999))
    rms = (sum_squares / sample_count) ** 0.5 if sample_count else 0.0
    clipped_ratio = clipped_count / sample_count if sample_count else 1.0
    if rms < 0.002:
        raise RuntimeError(f"Final narration RMS is unexpectedly low: {rms:.6f}")
    if peak >= 1.0 or clipped_ratio > 0.0001:
        raise RuntimeError(f"Final narration clipping gate failed: peak={peak:.6f}")
    return {
        "sample_rate": SAMPLE_RATE,
        "channels": 1,
        "subtype": info.subtype,
        "duration_seconds": round(float(info.duration), 4),
        "bytes": path.stat().st_size,
        "peak": round(peak, 6),
        "rms": round(rms, 6),
        "clipped_ratio": round(clipped_ratio, 8),
        "sha256": sha256_file(path),
        "checks": "passed",
    }


def build_rendered_chunks(payload: dict, builder: Any, temporary: Path) -> tuple[list[dict], dict]:
    language = payload["language"]
    engine = payload["engine"]
    selected_voice = payload["voice_id"]

    if engine == "piper":
        if language != "en":
            raise ValueError("Piper LibriTTS High is only enabled for English jobs")
        if payload.get("acknowledge_piper_restrictions") is not True:
            raise ValueError(
                "This Piper source is not blanket commercially cleared. "
                "Set acknowledge_piper_restrictions=true only after reviewing its rights note."
            )
        match = re.fullmatch(r"en-piper-libritts-high-(\d{4})", selected_voice)
        if not match:
            raise ValueError("Use a canonical Piper voice ID from the voice-library manifest")
        speaker_id = int(match.group(1))
        voice, piper_info = builder.prepare_piper()
        if speaker_id not in {sid for _, sid in piper_info["speaker_pairs"]}:
            raise ValueError(f"Unknown Piper speaker ID: {speaker_id}")
        speaker_name = dict((sid, name) for name, sid in piper_info["speaker_pairs"])[speaker_id]
        from piper import SynthesisConfig
        import wave

        def render(text: str, output: Path) -> None:
            with wave.open(str(output), "wb") as wav_file:
                voice.synthesize_wav(
                    text, wav_file, syn_config=SynthesisConfig(speaker_id=speaker_id)
                )

        source = {
            "engine": "Piper TTS 1.8.0",
            "model": "en_US-libritts-high",
            "revision": piper_info["revision"],
            "source_voice_id": speaker_name,
            "voice_id": selected_voice,
            "rights_status": "restricted-evidence",
            "commercial_use": "not-cleared-by-this-build",
            "notice": (
                "LibriTTS is identified as CC BY 4.0, but Piper documents voice-specific "
                "terms and personal/research-oriented use. This build does not grant "
                "speaker publicity or blanket commercial rights."
            ),
        }
    elif engine == "vieneu":
        tts, presets, vieneu_info = builder.prepare_vieneu()
        match_row = None
        for label, preset_id in presets:
            safe_id = builder.slugify(preset_id)
            identity_hash = hashlib.sha256(preset_id.encode("utf-8")).hexdigest()[:6]
            identity = f"vieneu-v3turbo-{safe_id}-{identity_hash}"
            canonical_id = f"{language}-{identity}"
            if selected_voice == canonical_id:
                match_row = (label, preset_id, identity)
                break
        if match_row is None:
            raise ValueError(
                "Unknown VieNeu voice ID. Use the language-specific canonical ID from manifest.json."
            )
        label, preset_id, identity = match_row

        def render(text: str, output: Path) -> None:
            builder.render_vieneu_wav(tts, preset_id, text, output)

        source = {
            "engine": f"VieNeu-TTS v3 Turbo {builder.VIENEU_PACKAGE_VERSION}",
            "model": builder.VIENEU_REPO,
            "revision": vieneu_info,
            "source_voice_id": preset_id,
            "display_name": label,
            "voice_identity_id": identity,
            "voice_id": selected_voice,
            "rights_status": "upstream-preset-consent-stated",
            "commercial_use": "upstream-model-card-permits-generated-audio",
            "notice": (
                "VieNeu's upstream model card states bundled preset consent and "
                "commercial use of generated audio; attribution and revision data are retained."
            ),
        }
    elif engine == "kokoro":
        if language != "en":
            raise ValueError("Kokoro-82M curated voices are English-only")
        prepared, voice_rows, kokoro_info = builder.prepare_kokoro()
        match_row = next(
            (row for row in voice_rows
             if selected_voice == f"en-kokoro-v1-{row['id']}"),
            None,
        )
        if match_row is None:
            raise ValueError(
                "Unknown Kokoro voice ID. Use a canonical en-kokoro-v1-* ID from manifest.json."
            )
        preset_id = str(match_row["id"])
        identity = f"kokoro-v1-{preset_id}"

        def render(text: str, output: Path) -> None:
            builder.render_kokoro_wav(prepared, preset_id, text, output)

        source = {
            "engine": f"Kokoro-82M {builder.KOKORO_PACKAGE_VERSION}",
            "model": builder.KOKORO_REPO,
            "revision": kokoro_info,
            "source_voice_id": preset_id,
            "display_name": str(match_row["display_name"]),
            "voice_identity_id": identity,
            "voice_id": selected_voice,
            "upstream_quality_grade": str(match_row["quality_grade"]),
            "quality_grade_source": "Kokoro upstream VOICES.md (subjective upstream rating)",
            "rights_status": "upstream-apache-2.0-model-voice-assets",
            "commercial_use": "apache-2.0-model-and-voice-assets",
            "notice": (
                "Kokoro model and packaged voice assets are marked Apache-2.0 upstream. "
                "Its quality grade is a subjective upstream estimate, not an independent MOS test. "
                "No real-person publicity, endorsement or identity rights are granted; do not impersonate."
            ),
        }
    else:
        raise ValueError(f"Unsupported TTS engine: {engine}")

    rows: list[dict] = []
    planned = plan_rendered_chunks(payload["segments"])

    parts: list[Path] = []
    timeline: list[dict] = []
    elapsed = 0.0
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required")
    import soundfile as sf

    for index, item in enumerate(planned, 1):
        raw = temporary / f"raw-{index:04d}.wav"
        converted = temporary / f"part-{index:04d}.wav"
        render(item["text"], raw)
        if not raw.is_file() or raw.stat().st_size < 2048:
            raise RuntimeError(f"TTS engine produced no usable audio for segment {item['source_id']}")
        resample_video_part(raw, converted)
        info = sf.info(str(converted))
        start = elapsed
        end = start + float(info.duration)
        timeline.append({
            "index": index,
            "id": item["source_id"],
            "chunk_index": item["chunk_index"],
            "chunk_count": item["chunk_count"],
            "text": item["text"],
            "start_seconds": round(start, 4),
            "end_seconds": round(end, 4),
            "duration_seconds": round(float(info.duration), 4),
            "pause_ms_after": item["pause_ms_after"],
        })
        parts.append(converted)
        elapsed = end

        pause_ms = item["pause_ms_after"]
        if pause_ms > 0:
            pause = temporary / f"pause-{index:04d}.wav"
            silence_frames = round(SAMPLE_RATE * pause_ms / 1000)
            import numpy as np
            sf.write(str(pause), np.zeros(silence_frames, dtype=np.float32), SAMPLE_RATE, subtype="PCM_24")
            parts.append(pause)
            elapsed += pause_ms / 1000.0

        if index % 5 == 0 or index == len(planned):
            log(f"Rendered {index}/{len(planned)} narration chunks")

    concat_list = temporary / "concat.txt"
    concat_list.write_text(
        "".join(f"file '{part.as_posix()}'\n" for part in parts), encoding="utf-8"
    )
    raw_master = temporary / "master-raw.wav"
    run_ffmpeg([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s24le",
        str(raw_master),
    ])
    return timeline, {"voice": source, "raw_master": raw_master, "rendered_chunk_count": len(planned)}


def deterministic_zip(output: Path, archive: Path) -> None:
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4) as zf:
        for path in sorted(output.iterdir()):
            if not path.is_file() or path.name == archive.name:
                continue
            info = zipfile.ZipInfo(path.name)
            info.date_time = (2020, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            with path.open("rb") as source, zf.open(info, "w") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)


def render_job(payload: dict, output: Path) -> int:
    import torch

    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    builder = load_builder()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="voice-video-job-") as temp_name:
        temporary = Path(temp_name)
        timeline, source = build_rendered_chunks(payload, builder, temporary)
        mastered = temporary / "master-loudnorm.wav"
        normalize_master(source["raw_master"], mastered)
        final_wav = output / "narration.wav"
        watermark = stream_watermark_and_verify(
            mastered, final_wav, context=f"video-job.{payload.get('job_id', 'unnamed')}"
        )
        audio = validate_final_audio(final_wav)
        write_captions(timeline, output)

        job_id = payload.get("job_id") or safe_slug(payload.get("title", "video-narration"))
        manifest = {
            "schema_version": 1,
            "job_id": job_id,
            "title": payload.get("title", "Video narration"),
            "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "language": payload["language"],
            "engine": payload["engine"],
            "voice_id": payload["voice_id"],
            "voice_source": source["voice"],
            "audio": {
                **audio,
                "file": "narration.wav",
                "target_loudness_lufs": TARGET_LUFS,
                "true_peak_ceiling_dbtp": TRUE_PEAK_DBTP,
                "watermark": watermark,
            },
            "segment_count": len(timeline),
            "segments": timeline,
            "captions": ["captions.srt", "captions.vtt"],
            "text_sha256": hashlib.sha256(
                "\n".join(row["text"] for row in timeline).encode("utf-8")
            ).hexdigest(),
            "quality_note": (
                "Signal, loudness, format and per-block watermark checks are machine gates; "
                "a human listening review remains necessary for editorial quality."
            ),
        }
        (output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (output / "build-summary.txt").write_text(
            "\n".join([
                "VoiceStudio video narration render",
                f"Job: {job_id}",
                f"Language: {payload['language']}",
                f"Voice: {payload['voice_id']}",
                f"Engine: {payload['engine']}",
                f"Chunks: {len(timeline)}",
                f"Duration: {audio['duration_seconds']:.2f}s",
                f"Audio: {audio['sample_rate']} Hz, {audio['subtype']}, {audio['channels']} channel",
                f"AudioSeal blocks verified: {watermark['block_count']}",
                f"SHA-256: {audio['sha256']}",
                "",
            ]),
            encoding="utf-8",
        )
    deterministic_zip(output, output / "video-voice-assets.zip")
    log(
        f"COMPLETE job={payload.get('job_id', 'unnamed')} "
        f"duration={audio['duration_seconds']:.1f}s chunks={len(timeline)} "
        f"watermark_blocks={watermark['block_count']}"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="dist/video-voice")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.check:
        import jsonschema
        sample = json.loads((ROOT / "voice-library" / "video-job.example.vi.json").read_text(encoding="utf-8"))
        validate_job_payload(sample)
        jsonschema.validate(sample, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
        assert split_text("Một câu. Câu thứ hai!") == ["Một câu. Câu thứ hai!"]
        assert len(plan_rendered_chunks([
            {"id": f"segment-{index}", "text": "First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence."}
            for index in range(38)
        ])) == 38
        assert format_timestamp(65.25) == "00:01:05,250"
        log("video narration payload/schema/chunking contract passed")
        return 0

    raw = os.environ.get("VOICE_JOB_JSON", "")
    if not raw.strip():
        raise ValueError("Set VOICE_JOB_JSON to a video-job JSON object")
    if len(raw) > 65_535:
        raise ValueError("VOICE_JOB_JSON exceeds GitHub's 65,535-character input limit")
    payload = validate_job_payload(json.loads(raw))
    log(
        f"Starting job={payload.get('job_id', 'unnamed')} "
        f"language={payload['language']} engine={payload['engine']} "
        f"voice={payload['voice_id']} segments={len(payload['segments'])}"
    )
    return render_job(payload, Path(args.output).resolve())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log("cancelled")
        raise SystemExit(130)
    except Exception as exc:
        log(f"FATAL: {type(exc).__name__}: {exc}")
        raise
