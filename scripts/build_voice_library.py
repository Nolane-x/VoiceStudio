#!/usr/bin/env python3
"""Build the English + Vietnamese VoiceStudio voice library.

All inference happens in GitHub Actions. Generated WAVs are intentionally
published as release assets rather than committed to Git history.

The English pack uses the 904-speaker Piper LibriTTS High ONNX model. The
Vietnamese pack uses every preset exposed by a pinned VieNeu-TTS v3 Turbo
SDK. VieNeu presets are also rendered in English so bilingual speaker
identities can be auditioned in both target languages.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
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
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

PIPER_REPO = "rhasspy/piper-voices"
PIPER_REVISION = "49a0d23f04e055f1766e5ad15ea2d121a90fa17a"
PIPER_KEY = "en_US-libritts-high"
PIPER_MODEL = "en/en_US/libritts/high/en_US-libritts-high.onnx"
PIPER_CARD = "en/en_US/libritts/high/MODEL_CARD"
PIPER_EXPECTED_SIZE = 136_673_811
PIPER_EXPECTED_MD5 = "61d7845257f8abdc27476f606151ef8d"
PIPER_EXPECTED_SPEAKERS = 904

VIENEU_PACKAGE_VERSION = "3.8.3"
VIENEU_REPO = "pnnbao-ump/VieNeu-TTS-v3-Turbo"
VIENEU_CODEC_REPO = "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX"

KOKORO_PACKAGE_VERSION = "0.9.4"
MISAKI_PACKAGE_VERSION = "0.9.4"
KOKORO_REPO = "hexgrad/Kokoro-82M"
KOKORO_MODEL_REVISION = "f3ff3571791e39611d31c381e3a41a3af07b4987"
KOKORO_VOICES_REVISION = "c3327e9bac3dbe55779397bfa82de0f8806fb3bc"
KOKORO_MODEL_FILE = "kokoro-v1_0.pth"
KOKORO_MODEL_SHA256 = "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4"
KOKORO_SAMPLE_RATE = 24_000
KOKORO_VOICE_IDS = {"af_heart", "af_bella", "af_nicole", "bf_emma"}

EN_TEXT = (
    "Welcome to your next story. Take a moment, settle in, and let every "
    "word bring the scene to life. This voice is made for clear narration, "
    "thoughtful pauses, and a warm connection with the listener."
)
VI_TEXT = (
    "Xin chào, rất vui được đồng hành cùng bạn. Hãy cùng khám phá câu "
    "chuyện hôm nay với chất giọng tự nhiên, rõ ràng và truyền cảm. "
    "Mỗi câu nói đều có nhịp điệu riêng, nhẹ nhàng nhưng vẫn cuốn hút."
)

TARGETS = {
    "en": {"sample_rate": 22_050, "bits": 16},
    "vi": {"sample_rate": 48_000, "bits": 24},
}
QUALITY = {
    "min_duration_s": 3.0,
    "max_duration_s": 35.0,
    "min_rms": 0.004,
    "max_silence_ratio": 0.62,
    "max_clipped_ratio": 0.001,
    "loudness_lufs": -18.0,
    "true_peak_dbtp": -1.5,
    "lra": 7,
}
MANIFEST_SCHEMA = ROOT / "voice-library" / "manifest.schema.json"
SOURCES_PATH = ROOT / "voice-library" / "sources.json"
ATTRIBUTION_PATH = ROOT / "voice-library" / "ATTRIBUTION.md"


def log(message: str) -> None:
    print(f"[voice-library] {message}", flush=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_sources() -> dict:
    data = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    assert data.get("schema_version") == 1, "Unsupported source registry schema"
    assert data.get("language_scope") == ["en", "vi"], "Only English and Vietnamese are allowed"
    english = data["english"]
    vietnamese = data["vietnamese"]
    shared = data["shared"]
    assert english["model_repo"] == PIPER_REPO
    assert english["model_revision"] == PIPER_REVISION
    assert english["model_key"] == PIPER_KEY
    assert english["expected_speakers"] == PIPER_EXPECTED_SPEAKERS
    assert vietnamese["model_repo"] == VIENEU_REPO
    assert vietnamese["sdk_package"] == f"vieneu=={VIENEU_PACKAGE_VERSION}"
    assert shared["watermark_required"] is True
    assert shared["verification"] == "VoiceStudio services.watermark.detect_watermark"
    kokoro = data["kokoro_english"]
    assert kokoro["model_repo"] == KOKORO_REPO
    assert kokoro["model_revision"] == KOKORO_MODEL_REVISION
    assert kokoro["voices_metadata_revision"] == KOKORO_VOICES_REVISION
    assert kokoro["engine_package"] == f"kokoro=={KOKORO_PACKAGE_VERSION}"
    assert {voice["id"] for voice in kokoro["selected_voices"]} == KOKORO_VOICE_IDS
    assert set(shared["formats"]) == {"piper", "vieneu", "kokoro"}
    return data


def check_static_contract() -> None:
    sources = load_sources()
    schema = json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))
    assert schema.get("$schema", "").endswith("2020-12/schema")
    assert {"schema_version", "library", "built_at", "counts", "voices", "rejected"} <= set(
        schema.get("required", [])
    )
    assert ATTRIBUTION_PATH.is_file()
    attribution = ATTRIBUTION_PATH.read_text(encoding="utf-8")
    assert "LibriTTS" in attribution and "VieNeu-TTS" in attribution and "Kokoro-82M" in attribution
    assert "AudioSeal" in attribution or "watermark" in attribution.lower()
    assert "vi" in sources["language_scope"] and "en" in sources["language_scope"]
    log("static source, schema, language-scope and attribution checks passed")


def hf_download(repo_id: str, filename: str, revision: str | None = None) -> Path:
    from huggingface_hub import hf_hub_download

    return Path(
        hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            revision=revision,
            repo_type="model",
        )
    )


def hf_revision(repo_id: str) -> str:
    from huggingface_hub import HfApi

    info = HfApi().model_info(repo_id, files_metadata=False)
    sha = getattr(info, "sha", None)
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError(f"Could not resolve an immutable Hugging Face revision for {repo_id}")
    return sha


def prepare_piper() -> tuple[Any, dict]:
    """Download and verify the exact Piper voice/model files, then load once."""
    from piper import PiperVoice

    voices_path = hf_download(PIPER_REPO, "voices.json", PIPER_REVISION)
    voices = json.loads(voices_path.read_text(encoding="utf-8"))
    entry = voices.get(PIPER_KEY)
    if not isinstance(entry, dict):
        raise RuntimeError(f"{PIPER_KEY} is missing from the pinned Piper voices.json")
    if entry.get("quality") != "high":
        raise RuntimeError("Pinned Piper source no longer identifies this model as high quality")
    if int(entry.get("num_speakers", 0)) != PIPER_EXPECTED_SPEAKERS:
        raise RuntimeError("Piper speaker count differs from the reviewed source record")

    speaker_map = entry.get("speaker_id_map")
    if not isinstance(speaker_map, dict) or len(speaker_map) != PIPER_EXPECTED_SPEAKERS:
        raise RuntimeError("Piper speaker_id_map is missing or incomplete")
    speaker_pairs = sorted(
        ((str(name), int(speaker_id)) for name, speaker_id in speaker_map.items()),
        key=lambda item: item[1],
    )
    expected_ids = list(range(PIPER_EXPECTED_SPEAKERS))
    if [speaker_id for _, speaker_id in speaker_pairs] != expected_ids:
        raise RuntimeError("Piper speaker IDs are not a complete zero-based range")

    files = entry.get("files") or {}
    metadata = files.get(PIPER_MODEL)
    config_rel = PIPER_MODEL + ".json"
    config_meta = files.get(config_rel)
    card_meta = files.get(PIPER_CARD)
    for label, value in (("model", metadata), ("config", config_meta), ("model card", card_meta)):
        if not isinstance(value, dict):
            raise RuntimeError(f"Piper voices.json lacks {label} file metadata")

    if int(metadata.get("size_bytes", -1)) != PIPER_EXPECTED_SIZE:
        raise RuntimeError("Piper ONNX model size changed; re-review the source pin")
    if str(metadata.get("md5_digest", "")).lower() != PIPER_EXPECTED_MD5:
        raise RuntimeError("Piper ONNX model MD5 differs from the reviewed source pin")

    model_path = hf_download(PIPER_REPO, PIPER_MODEL, PIPER_REVISION)
    config_path = hf_download(PIPER_REPO, config_rel, PIPER_REVISION)
    card_path = hf_download(PIPER_REPO, PIPER_CARD, PIPER_REVISION)
    if model_path.stat().st_size != PIPER_EXPECTED_SIZE:
        raise RuntimeError("Downloaded Piper ONNX file has an unexpected size")
    if md5_file(model_path) != PIPER_EXPECTED_MD5:
        raise RuntimeError("Downloaded Piper ONNX file failed the pinned MD5 check")
    for label, path, expected in (
        ("Piper config", config_path, config_meta),
        ("Piper model card", card_path, card_meta),
    ):
        if path.stat().st_size != int(expected["size_bytes"]):
            raise RuntimeError(f"Downloaded {label} failed the source size check")
        if md5_file(path) != str(expected["md5_digest"]).lower():
            raise RuntimeError(f"Downloaded {label} failed the source MD5 check")

    card_text = card_path.read_text(encoding="utf-8")
    for required in ("904", "high", "22,050", "CC BY 4.0", "train-clean-360"):
        if required.lower() not in card_text.lower():
            raise RuntimeError(f"Piper model card no longer contains the reviewed field: {required}")

    voice = PiperVoice.load(model_path, config_path=config_path, use_cuda=False)
    if int(voice.config.num_speakers) != PIPER_EXPECTED_SPEAKERS:
        raise RuntimeError("Loaded Piper model speaker count differs from the source registry")

    revision = {
        "repo": PIPER_REPO,
        "revision": PIPER_REVISION,
        "model_sha256": sha256_file(model_path),
        "model_md5": md5_file(model_path),
        "model_size_bytes": model_path.stat().st_size,
        "config_sha256": sha256_file(config_path),
        "voices_json_sha256": sha256_file(voices_path),
        "model_card_sha256": sha256_file(card_path),
        "quality": entry["quality"],
        "speaker_count": len(speaker_pairs),
        "sample_rate": int(voice.config.sample_rate),
        "license_note": "LibriTTS dataset is identified as CC BY 4.0; this is not blanket speaker/publicity/commercial clearance.",
    }
    log(f"Piper loaded: {len(speaker_pairs)} speaker IDs, {voice.config.sample_rate} Hz")
    return voice, {"speaker_pairs": speaker_pairs, "revision": revision}


def _download_vieneu_local_assets(
    model_revision: str,
    codec_revision: str,
) -> tuple[Path, Path]:
    """Materialize ONNX graphs and external-data tensors into ordinary local dirs.

    HF Hub's immutable cache paths are per-file blobs. ONNX external-data
    validation requires the graph and its shared .data tensor to resolve
    inside one directory, so opening cache symlinks directly is rejected by
    ONNX Runtime. local_dir downloads preserve the repository-relative layout
    with real files; every file remains pinned to the exact model/codec SHA.
    """
    import huggingface_hub

    original_download = huggingface_hub.hf_hub_download
    base = Path(tempfile.gettempdir()) / "voice-library-vieneu"
    model_root = base / "vieneu-model"
    codec_root = base / "moss-codec"
    model_root.mkdir(parents=True, exist_ok=True)
    codec_root.mkdir(parents=True, exist_ok=True)

    def download_local(
        repo_id: str,
        relative_name: str,
        revision: str,
        destination: Path,
    ) -> Path:
        target = destination / relative_name
        if target.is_file() and target.stat().st_size > 0:
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        downloaded = original_download(
            repo_id=repo_id,
            filename=relative_name,
            revision=revision,
            repo_type="model",
            local_dir=str(destination),
        )
        result = Path(downloaded)
        if not result.is_file() or result.stat().st_size <= 0:
            raise RuntimeError(f"Missing VieNeu asset after download: {repo_id}/{relative_name}")
        return result

    model_files = [
        "onnx_update/vieneu_prefill.onnx",
        "onnx_update/vieneu_decode_step.onnx",
        "onnx_update/vieneu_acoustic_cached.onnx",
        "onnx_update/vieneu_backbone_shared.data",
        "onnx_update/vieneu_v3_heads.npz",
        "onnx_update/config.json",
        "onnx_update/tokenizer.json",
    ]
    codec_files = [
        "moss_audio_tokenizer_decode_full.onnx",
        "moss_audio_tokenizer_decode_shared.data",
        "moss_audio_tokenizer_decode_step.onnx",
        "codec_browser_onnx_meta.json",
        "moss_audio_tokenizer_encode.onnx",
        "moss_audio_tokenizer_encode.data",
    ]
    for relative_name in model_files:
        download_local(VIENEU_REPO, relative_name, model_revision, model_root)
    for relative_name in codec_files:
        download_local(VIENEU_CODEC_REPO, relative_name, codec_revision, codec_root)

    repo_locations = {
        VIENEU_REPO: (model_root, model_revision),
        VIENEU_CODEC_REPO: (codec_root, codec_revision),
    }

    def local_hf_hub_download(repo_id, filename, *args, **kwargs):
        location = repo_locations.get(str(repo_id))
        if location is None:
            return original_download(repo_id, filename, *args, **kwargs)
        destination, pinned_revision = location
        subfolder = kwargs.pop("subfolder", None)
        relative_name = f"{subfolder}/{filename}" if subfolder else str(filename)
        target = destination / relative_name
        if target.is_file() and target.stat().st_size > 0:
            return str(target)
        revision = kwargs.pop("revision", None) or pinned_revision
        repo_type = kwargs.pop("repo_type", "model")
        downloaded = original_download(
            repo_id=repo_id,
            filename=relative_name,
            revision=revision,
            repo_type=repo_type,
            local_dir=str(destination),
            **kwargs,
        )
        return str(downloaded)

    # VieNeu 3.8.3 imports hf_hub_download lazily from the package root for
    # its model/codec helpers. Route only these two known model repos to the
    # local, SHA-pinned materialization; all unrelated Hub downloads retain
    # the upstream implementation.
    huggingface_hub.hf_hub_download = local_hf_hub_download
    return model_root, codec_root


def prepare_vieneu() -> tuple[Any, list[tuple[str, str]], dict]:
    """Load VieNeu's public, CPU/ONNX, FP32 path and enumerate its actual presets."""
    import importlib.metadata

    installed = importlib.metadata.version("vieneu")
    if installed != VIENEU_PACKAGE_VERSION:
        raise RuntimeError(f"Expected vieneu {VIENEU_PACKAGE_VERSION}, found {installed}")

    from vieneu import Vieneu

    model_revision = hf_revision(VIENEU_REPO)
    codec_revision = hf_revision(VIENEU_CODEC_REPO)
    model_root, codec_root = _download_vieneu_local_assets(model_revision, codec_revision)
    tts = Vieneu(
        mode="v3turbo",
        # The package ships its reviewed built-in preset roster. A repo-root
        # voices_v3_turbo.json is optional and absent from this model revision.
        backbone_repo=str(model_root),
        moss_tokenizer=VIENEU_CODEC_REPO,
        onnx_repo=VIENEU_REPO,
        onnx_dir=str(model_root / "onnx_update"),
        device="cpu",
        backend="onnx",
        precision="fp32",
        threads=max(1, min(4, os.cpu_count() or 1)),
    )
    presets = tts.list_preset_voices()
    if not isinstance(presets, list) or len(presets) < 20:
        raise RuntimeError(
            f"VieNeu exposed only {len(presets) if isinstance(presets, list) else 0} presets; "
            "the reviewed minimum is 20"
        )
    identities: set[str] = set()
    for row in presets:
        if not isinstance(row, (tuple, list)) or len(row) != 2:
            raise RuntimeError("Unexpected VieNeu preset entry; expected (label, voice_id)")
        label, voice_id = str(row[0]).strip(), str(row[1]).strip()
        if not label or not voice_id or voice_id in identities:
            raise RuntimeError("VieNeu returned an empty or duplicate preset identity")
        identities.add(voice_id)
        tts.get_preset_voice(voice_id)

    revision = {
        "sdk": "vieneu",
        "sdk_version": installed,
        "sdk_source": "https://github.com/pnnbao97/VieNeu-TTS",
        "model_repo": VIENEU_REPO,
        "model_revision": model_revision,
        "codec_repo": VIENEU_CODEC_REPO,
        "codec_revision": codec_revision,
        "sample_rate": int(tts.sample_rate),
        "precision": "fp32",
        "backend": "onnx-cpu",
        "preset_count": len(presets),
        "preset_ids": [str(row[1]) for row in presets],
    }
    if int(tts.sample_rate) != TARGETS["vi"]["sample_rate"]:
        raise RuntimeError(f"VieNeu output rate changed unexpectedly: {tts.sample_rate}")
    log(f"VieNeu loaded: {len(presets)} preset identities, {tts.sample_rate} Hz")
    return tts, [(str(label), str(voice_id)) for label, voice_id in presets], revision


def prepare_kokoro() -> tuple[dict, list[dict], dict]:
    """Load the immutable Kokoro checkpoint and only reviewed A/B-grade English voices."""
    import importlib.metadata
    import torch
    from kokoro.model import KModel
    from kokoro.pipeline import KPipeline

    installed = importlib.metadata.version("kokoro")
    if installed != KOKORO_PACKAGE_VERSION:
        raise RuntimeError(f"Expected kokoro {KOKORO_PACKAGE_VERSION}, found {installed}")
    misaki_version = importlib.metadata.version("misaki")
    if misaki_version != MISAKI_PACKAGE_VERSION:
        raise RuntimeError(f"Expected misaki {MISAKI_PACKAGE_VERSION}, found {misaki_version}")

    sources = load_sources()["kokoro_english"]
    model_path = hf_download(KOKORO_REPO, KOKORO_MODEL_FILE, KOKORO_MODEL_REVISION)
    config_path = hf_download(KOKORO_REPO, "config.json", KOKORO_MODEL_REVISION)
    voices_doc_path = hf_download(KOKORO_REPO, "VOICES.md", KOKORO_VOICES_REVISION)
    model_sha256 = sha256_file(model_path)
    if model_sha256 != KOKORO_MODEL_SHA256:
        raise RuntimeError(
            "Kokoro checkpoint SHA-256 changed; re-review the upstream model revision "
            f"(expected {KOKORO_MODEL_SHA256}, got {model_sha256})"
        )
    voices_doc = voices_doc_path.read_text(encoding="utf-8")
    selected = sources["selected_voices"]
    voice_tensors: dict[str, Any] = {}
    voice_file_hashes: dict[str, str] = {}
    for item in selected:
        voice_id = str(item["id"])
        if voice_id not in KOKORO_VOICE_IDS:
            raise RuntimeError(f"Unreviewed Kokoro voice ID in source registry: {voice_id}")
        row_cells = None
        for line in voices_doc.splitlines():
            if "|" not in line:
                continue
            cells_candidate = [
                re.sub(r"[*`]", "", cell).strip()
                for cell in line.strip().strip("|").split("|")
            ]
            if cells_candidate and cells_candidate[0] == voice_id:
                row_cells = cells_candidate
                break
        if row_cells is None:
            raise RuntimeError(f"Kokoro VOICES.md does not contain {voice_id}")
        cells = row_cells
        if len(cells) < 6 or cells[0] != voice_id:
            raise RuntimeError(f"Unexpected Kokoro voice-grade row for {voice_id}: {cells}")
        if cells[4] != str(item["quality_grade"]):
            raise RuntimeError(f"Kokoro upstream grade changed for {voice_id}: {cells[4]}")
        if cells[5] != str(item["voice_sha256_prefix"]):
            raise RuntimeError(f"Kokoro voice SHA prefix changed for {voice_id}: {cells[5]}")

        voice_path = hf_download(KOKORO_REPO, f"voices/{voice_id}.pt", KOKORO_MODEL_REVISION)
        voice_sha256 = sha256_file(voice_path)
        if not voice_sha256.startswith(str(item["voice_sha256_prefix"])):
            raise RuntimeError(f"Kokoro voice embedding checksum mismatch for {voice_id}")
        tensor = torch.load(voice_path, map_location="cpu", weights_only=True)
        if not isinstance(tensor, torch.Tensor) or tensor.dtype != torch.float32:
            raise RuntimeError(f"Kokoro voice embedding has an unexpected tensor type: {voice_id}")
        if not torch.isfinite(tensor).all():
            raise RuntimeError(f"Kokoro voice embedding contains invalid values: {voice_id}")
        voice_tensors[voice_id] = tensor
        voice_file_hashes[voice_id] = voice_sha256

    model = KModel(
        repo_id=KOKORO_REPO,
        config=str(config_path),
        model=str(model_path),
    ).to("cpu").eval()
    # American and British English need distinct G2P pipelines, but the
    # exact same immutable model weights are shared between both pipelines.
    pipelines = {
        "a": KPipeline(lang_code="a", repo_id=KOKORO_REPO, model=model, device="cpu"),
        "b": KPipeline(lang_code="b", repo_id=KOKORO_REPO, model=model, device="cpu"),
    }
    prepared = {"pipelines": pipelines, "voice_tensors": voice_tensors}
    revision = {
        "repo": KOKORO_REPO,
        "model_revision": KOKORO_MODEL_REVISION,
        "model_file": KOKORO_MODEL_FILE,
        "model_sha256": model_sha256,
        "config_sha256": sha256_file(config_path),
        "voices_metadata_revision": KOKORO_VOICES_REVISION,
        "voices_metadata_sha256": sha256_file(voices_doc_path),
        "package": installed,
        "misaki": misaki_version,
        "sample_rate": KOKORO_SAMPLE_RATE,
        "device": "cpu",
        "selected_voices": [
            {
                "id": item["id"],
                "quality_grade": item["quality_grade"],
                "voice_sha256": voice_file_hashes[item["id"]],
            }
            for item in selected
        ],
    }
    log(f"Kokoro loaded: {len(selected)} curated English presets, {KOKORO_SAMPLE_RATE} Hz")
    return prepared, selected, revision


def run_ffmpeg_normalize(source: Path, target: Path, sample_rate: int, bits: int) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to normalize the library audio")
    codec = "pcm_s16le" if bits == 16 else "pcm_s24le"
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source),
        "-af", f"loudnorm=I={QUALITY['loudness_lufs']}:TP={QUALITY['true_peak_dbtp']}:LRA={QUALITY['lra']}",
        "-ar", str(sample_rate),
        "-ac", "1",
        "-c:a", codec,
        "-map_metadata", "-1",
        str(target),
    ]
    subprocess.run(command, check=True, timeout=180, capture_output=True, text=True)
    if not target.is_file() or target.stat().st_size < 2048:
        raise RuntimeError("ffmpeg did not produce a valid normalized WAV")


def watermark_and_verify(path: Path, bits: int, context: str) -> dict:
    """Apply VoiceStudio's provenance mark and verify the saved WAV, not a tensor."""
    import torch
    import torchaudio
    from services.watermark import detect_watermark, mark_synthetic

    waveform, sample_rate = torchaudio.load(str(path))
    if waveform.ndim != 2 or waveform.shape[0] != 1:
        raise RuntimeError("Library audio must be mono before watermarking")
    marked = mark_synthetic(
        waveform.to(torch.float32),
        int(sample_rate),
        context=context,
        force=True,
    )
    temp = path.with_name(path.stem + ".marked.wav")
    torchaudio.save(
        str(temp),
        marked.to(torch.float32),
        int(sample_rate),
        encoding="PCM_S",
        bits_per_sample=bits,
    )
    os.replace(temp, path)

    decoded, decoded_rate = torchaudio.load(str(path))
    verdict = detect_watermark(decoded.to(torch.float32), int(decoded_rate))
    if not verdict.get("is_watermarked") or not verdict.get("is_omnivoice"):
        raise RuntimeError(
            "VoiceStudio AudioSeal watermark could not be verified after saving "
            f"(confidence={verdict.get('confidence')}, error={verdict.get('error')})"
        )
    return {
        "watermark": "verified",
        "watermark_source": verdict.get("source", "VoiceStudio"),
        "watermark_confidence": float(verdict.get("confidence", 0.0)),
        "watermark_message_bits": verdict.get("message_bits", ""),
    }


def validate_audio(path: Path, expected_sample_rate: int, expected_bits: int) -> dict:
    import numpy as np
    import soundfile as sf

    info = sf.info(str(path))
    audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    # FFmpeg emits WAVE_FORMAT_EXTENSIBLE (WAVEX) for some valid PCM-24
    # streams. Accept both RIFF WAV containers, but enforce the exact PCM
    # subtype so this does not accidentally admit float or compressed audio.
    if info.format not in {"WAV", "WAVEX"}:
        raise RuntimeError(f"Expected a WAV container, got {info.format}")
    expected_subtype = {16: "PCM_16", 24: "PCM_24"}.get(int(expected_bits))
    if expected_subtype is None or info.subtype != expected_subtype:
        raise RuntimeError(
            f"Expected {expected_subtype or 'supported PCM'} samples, got {info.subtype}"
        )
    if int(sample_rate) != int(expected_sample_rate):
        raise RuntimeError(f"Sample-rate mismatch: {sample_rate} != {expected_sample_rate}")
    if info.channels != 1:
        raise RuntimeError(f"Expected mono, got {info.channels} channels")
    if not np.isfinite(audio).all():
        raise RuntimeError("Audio contains NaN or infinite samples")
    if audio.size == 0:
        raise RuntimeError("Audio is empty")
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))
    duration = float(len(audio) / sample_rate)
    silence_ratio = float(np.mean(np.abs(audio[:, 0]) < 0.002))
    clipped_ratio = float(np.mean(np.abs(audio[:, 0]) >= 0.999))
    if not QUALITY["min_duration_s"] <= duration <= QUALITY["max_duration_s"]:
        raise RuntimeError(f"Duration out of range: {duration:.2f}s")
    if rms < QUALITY["min_rms"]:
        raise RuntimeError(f"Audio RMS too low: {rms:.6f}")
    if silence_ratio > QUALITY["max_silence_ratio"]:
        raise RuntimeError(f"Too much near-silence: {silence_ratio:.1%}")
    if clipped_ratio > QUALITY["max_clipped_ratio"]:
        raise RuntimeError(f"Clipping ratio too high: {clipped_ratio:.4%}")
    return {
        "sample_rate": int(sample_rate),
        "channels": int(info.channels),
        "subtype": info.subtype,
        "duration_seconds": round(duration, 4),
        "bytes": path.stat().st_size,
        "peak": round(peak, 6),
        "rms": round(rms, 6),
        "near_silence_ratio": round(silence_ratio, 5),
        "clipped_ratio": round(clipped_ratio, 6),
        "sha256": sha256_file(path),
    }


def slugify(value: str, max_length: int = 48) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_value = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
    return (ascii_value[:max_length].strip("-") or "voice")


def render_piper_wav(voice: Any, speaker_id: int, output: Path) -> None:
    from piper import SynthesisConfig
    import wave

    output.parent.mkdir(parents=True, exist_ok=True)
    config = SynthesisConfig(speaker_id=int(speaker_id))
    with wave.open(str(output), "wb") as wav_file:
        voice.synthesize_wav(EN_TEXT, wav_file, syn_config=config)


def render_vieneu_wav(tts: Any, voice_id: str, text: str, output: Path) -> None:
    import numpy as np
    import soundfile as sf

    audio = tts.infer(
        text,
        voice=voice_id,
        apply_watermark=False,
        batch_size=1,
    )
    samples = np.asarray(audio, dtype=np.float32)
    if samples.ndim == 2:
        if samples.shape[0] == 1:
            samples = samples[0]
        elif samples.shape[1] == 1:
            samples = samples[:, 0]
        else:
            raise RuntimeError(f"Unexpected VieNeu audio shape: {samples.shape}")
    if samples.ndim != 1:
        raise RuntimeError(f"Unexpected VieNeu waveform dimensions: {samples.shape}")
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output), samples, int(tts.sample_rate), subtype="FLOAT", format="WAV")


def render_kokoro_wav(
    prepared: dict,
    voice_id: str,
    text: str,
    output: Path,
) -> None:
    """Render one English sample with the pinned Kokoro voice embedding."""
    import numpy as np
    import soundfile as sf

    if voice_id not in prepared["voice_tensors"]:
        raise ValueError(f"Unknown or unverified Kokoro voice: {voice_id}")
    language_code = voice_id[0]
    pipeline = prepared["pipelines"].get(language_code)
    if pipeline is None:
        raise ValueError(f"Unsupported Kokoro language prefix: {voice_id}")
    voice_tensor = prepared["voice_tensors"][voice_id]
    generated = pipeline(text, voice=voice_tensor, speed=1.0, split_pattern=r"\n+")
    chunks: list[np.ndarray] = []
    for result in generated:
        audio = getattr(result, "audio", None)
        if audio is None:
            continue
        samples = audio.detach().cpu().numpy().astype(np.float32, copy=False)
        samples = np.squeeze(samples)
        if samples.ndim != 1 or not np.isfinite(samples).all():
            raise RuntimeError(f"Kokoro returned an invalid waveform for {voice_id}")
        if samples.size:
            chunks.append(samples)
    if not chunks:
        raise RuntimeError(f"Kokoro generated no audio for {voice_id}")
    silence = np.zeros(round(KOKORO_SAMPLE_RATE * 0.18), dtype=np.float32)
    joined: list[np.ndarray] = []
    for index, chunk in enumerate(chunks):
        if index:
            joined.append(silence)
        joined.append(chunk)
    waveform = np.concatenate(joined)
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output), waveform, KOKORO_SAMPLE_RATE, subtype="FLOAT", format="WAV")


def render_one(
    *,
    voice_id: str,
    identity_id: str,
    display_name: str,
    language: str,
    engine: str,
    model: str,
    sample_text: str,
    sample_rate: int,
    bits: int,
    output_dir: Path,
    render: Callable[[Path], None],
    rights: dict,
    source_voice_id: str | None = None,
    source_quality_grade: str | None = None,
) -> dict:
    destination = output_dir / language / f"{voice_id}.wav"
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="voice-library-") as temporary:
            raw = Path(temporary) / "raw.wav"
            normalized = Path(temporary) / "normalized.wav"
            render(raw)
            if not raw.is_file() or raw.stat().st_size < 2048:
                raise RuntimeError("Renderer did not create a non-empty WAV")
            run_ffmpeg_normalize(raw, normalized, sample_rate, bits)
            watermark = watermark_and_verify(
                normalized, bits, context=f"voice-library.{language}.{voice_id}"
            )
            audio = validate_audio(normalized, sample_rate, bits)
            shutil.copy2(normalized, destination)
        return {
            "id": voice_id,
            "language": language,
            "display_name": display_name,
            "voice_identity_id": identity_id,
            "source_voice_id": source_voice_id,
            "upstream_quality_grade": source_quality_grade,
            "quality_grade_source": "Kokoro upstream VOICES.md" if source_quality_grade else None,
            "engine": engine,
            "model": model,
            "audio_file": f"voices/{voice_id}.wav",
            "audio_sha256": audio["sha256"],
            "sample_rate": audio["sample_rate"],
            "channels": audio["channels"],
            "subtype": audio["subtype"],
            "duration_seconds": audio["duration_seconds"],
            "bytes": audio["bytes"],
            "sample_text": sample_text,
            "watermark": "verified",
            "watermark_confidence": watermark["watermark_confidence"],
            "signal_checks": {
                "finite": True,
                "rms": audio["rms"],
                "peak": audio["peak"],
                "near_silence_ratio": audio["near_silence_ratio"],
                "clipped_ratio": audio["clipped_ratio"],
                "status": "passed",
            },
            "rights": rights,
        }
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def add_with_rejection(
    voices: list[dict],
    rejected: list[dict],
    *,
    voice_id: str,
    display_name: str,
    language: str,
    render_kwargs: dict,
) -> None:
    try:
        result = render_one(
            voice_id=voice_id,
            display_name=display_name,
            language=language,
            **render_kwargs,
        )
        voices.append(result)
        log(
            f"PASS {language} {voice_id} "
            f"{result['duration_seconds']:.1f}s "
            f"watermark={result['watermark_confidence']:.3f}"
        )
    except Exception as exc:
        reason = f"{type(exc).__name__}: {str(exc)[:500]}"
        rejected.append({
            "id": voice_id,
            "language": language,
            "display_name": display_name,
            "reason": reason,
        })
        log(f"REJECT {language} {voice_id}: {reason}")


def deterministic_zip(base: Path, language: str, archive_path: Path, voices: list[dict]) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    language_voices = sorted(
        (voice for voice in voices if voice["language"] == language),
        key=lambda voice: voice["id"],
    )
    attribution = ATTRIBUTION_PATH.read_bytes()
    with zipfile.ZipFile(
        archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4
    ) as archive:
        for voice in language_voices:
            path = base / language / f"{voice['id']}.wav"
            info = zipfile.ZipInfo(voice["audio_file"])
            info.date_time = (2020, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=4)
        notice = zipfile.ZipInfo("ATTRIBUTION.txt")
        notice.date_time = (2020, 1, 1, 0, 0, 0)
        notice.compress_type = zipfile.ZIP_DEFLATED
        notice.external_attr = 0o100644 << 16
        archive.writestr(notice, attribution)


def build(args: argparse.Namespace) -> int:
    import torch

    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    output = Path(args.output).resolve()
    audio_root = output / "audio"
    output.mkdir(parents=True, exist_ok=True)
    audio_root.mkdir(parents=True, exist_ok=True)

    voices: list[dict] = []
    rejected: list[dict] = []
    source_revisions: dict = {}
    piper_expected = 0
    vieneu_expected = 0
    kokoro_expected = 0

    if args.language in ("all", "en"):
        piper, piper_info = prepare_piper()
        speaker_pairs = piper_info["speaker_pairs"]
        piper_revision = piper_info["revision"]
        source_revisions["piper"] = piper_revision
        selected = speaker_pairs[: args.limit] if args.limit else speaker_pairs
        piper_expected = len(selected)
        rights = {
            "source_license": "CC-BY-4.0 dataset license recorded on the voice model card",
            "rights_status": "restricted-evidence",
            "commercial_use": "not-cleared-by-this-build",
            "attribution_required": True,
            "source_url": (
                "https://huggingface.co/rhasspy/piper-voices/tree/"
                f"{PIPER_REVISION}/en/en_US/libritts/high"
            ),
            "notice": (
                "Piper's project documentation says voice terms vary and describes "
                "the engine as intended for personal use and TTS research. This "
                "record does not grant speaker publicity/endorsement rights or "
                "blanket commercial permission."
            ),
        }
        for index, (speaker_name, speaker_id) in enumerate(selected, 1):
            voice_id = f"en-piper-libritts-high-{speaker_id:04d}"
            add_with_rejection(
                voices, rejected,
                voice_id=voice_id,
                display_name=f"English (US) · LibriTTS Speaker {speaker_id + 1:03d}",
                language="en",
                render_kwargs={
                    "identity_id": f"piper-libritts-high-{speaker_id:04d}",
                    "engine": "Piper TTS 1.8.0",
                    "model": PIPER_KEY,
                    "sample_text": EN_TEXT,
                    "sample_rate": int(piper.config.sample_rate),
                    "bits": TARGETS["en"]["bits"],
                    "output_dir": audio_root,
                    "render": lambda raw, sid=speaker_id: render_piper_wav(piper, sid, raw),
                    "rights": rights,
                    "source_voice_id": speaker_name,
                },
            )
            if index % 25 == 0 or index == len(selected):
                log(f"Piper progress: {index}/{len(selected)}")
            if index % 10 == 0:
                write_json(output / "progress.json", {
                    "stage": "piper", "completed": index, "target": len(selected),
                    "accepted": len(voices), "rejected": len(rejected),
                })

    if args.language in ("all", "en"):
        kokoro, kokoro_voices, kokoro_info = prepare_kokoro()
        source_revisions["kokoro"] = kokoro_info
        chosen_kokoro = kokoro_voices[: args.limit] if args.limit else kokoro_voices
        kokoro_expected = len(chosen_kokoro)
        kokoro_rights = {
            "source_license": "Apache-2.0 model and packaged voice-embedding assets",
            "rights_status": "upstream-apache-2.0-model-voice-assets",
            "commercial_use": "apache-2.0-model-and-voice-assets",
            "attribution_required": True,
            "source_url": f"https://huggingface.co/{KOKORO_REPO}",
            "notice": (
                "The upstream model repository marks its model and packaged voice assets Apache-2.0 "
                "and describes the training audio as permissive or non-copyrighted. Its voice-grade "
                "labels are subjective upstream estimates, not independent MOS measurements. This "
                "does not grant real-person publicity, endorsement, or identity rights; do not impersonate."
            ),
        }
        for index, item in enumerate(chosen_kokoro, 1):
            source_id = str(item["id"])
            voice_id = f"en-kokoro-v1-{source_id}"
            add_with_rejection(
                voices, rejected,
                voice_id=voice_id,
                display_name=f"{item['display_name']} · Upstream grade {item['quality_grade']}",
                language="en",
                render_kwargs={
                    "identity_id": f"kokoro-v1-{source_id}",
                    "engine": f"Kokoro-82M {KOKORO_PACKAGE_VERSION}",
                    "model": KOKORO_REPO,
                    "sample_text": EN_TEXT,
                    "sample_rate": KOKORO_SAMPLE_RATE,
                    "bits": int(load_sources()["kokoro_english"]["bits_per_sample"]),
                    "output_dir": audio_root,
                    "render": lambda raw, vid=source_id: render_kokoro_wav(kokoro, vid, EN_TEXT, raw),
                    "rights": kokoro_rights,
                    "source_voice_id": source_id,
                    "source_quality_grade": str(item["quality_grade"]),
                },
            )
            if index % 2 == 0 or index == len(chosen_kokoro):
                write_json(output / "progress.json", {
                    "stage": "kokoro", "completed": index, "target": len(chosen_kokoro),
                    "accepted": len(voices), "rejected": len(rejected),
                })
        log(f"Kokoro progress: {len(chosen_kokoro)}/{len(chosen_kokoro)} curated English voices")

    if args.language in ("all", "vi", "en"):
        tts, presets, vieneu_info = prepare_vieneu()
        source_revisions["vieneu"] = vieneu_info
        chosen = presets[: args.limit] if args.limit else presets
        vieneu_expected = len(chosen)
        rights = {
            "source_license": "Apache-2.0",
            "rights_status": "upstream-preset-consent-stated",
            "commercial_use": "upstream-model-card-permits-generated-audio",
            "attribution_required": True,
            "source_url": f"https://huggingface.co/{VIENEU_REPO}",
            "notice": (
                "VieNeu's model card states that bundled preset voices were "
                "provided with speaker/rightsholder consent and that generated "
                "audio may be used commercially. The source model card and "
                "resolved model/codec revisions are included in this release."
            ),
        }
        for index, (label, voice_id) in enumerate(chosen, 1):
            safe_id = slugify(voice_id)
            identity_hash = hashlib.sha256(voice_id.encode("utf-8")).hexdigest()[:6]
            identity = f"vieneu-v3turbo-{safe_id}-{identity_hash}"
            tts.get_preset_voice(voice_id)
            if args.language in ("all", "vi"):
                vi_id = f"vi-{identity}"
                add_with_rejection(
                    voices, rejected,
                    voice_id=vi_id,
                    display_name=f"Tiếng Việt · {label}",
                    language="vi",
                    render_kwargs={
                        "identity_id": identity,
                        "engine": f"VieNeu-TTS v3 Turbo {VIENEU_PACKAGE_VERSION}",
                        "model": VIENEU_REPO,
                        "sample_text": VI_TEXT,
                        "sample_rate": int(tts.sample_rate),
                        "bits": TARGETS["vi"]["bits"],
                        "output_dir": audio_root,
                        "render": lambda raw, vid=voice_id: render_vieneu_wav(tts, vid, VI_TEXT, raw),
                        "rights": rights,
                        "source_voice_id": voice_id,
                    },
                )
            if args.language in ("all", "en"):
                en_id = f"en-{identity}"
                add_with_rejection(
                    voices, rejected,
                    voice_id=en_id,
                    display_name=f"English (bilingual) · {label}",
                    language="en",
                    render_kwargs={
                        "identity_id": identity,
                        "engine": f"VieNeu-TTS v3 Turbo {VIENEU_PACKAGE_VERSION}",
                        "model": VIENEU_REPO,
                        "sample_text": EN_TEXT,
                        "sample_rate": int(tts.sample_rate),
                        "bits": TARGETS["en"]["bits"],
                        "output_dir": audio_root,
                        "render": lambda raw, vid=voice_id: render_vieneu_wav(tts, vid, EN_TEXT, raw),
                        "rights": rights,
                        "source_voice_id": voice_id,
                    },
                )
            if index % 5 == 0 or index == len(chosen):
                log(f"VieNeu progress: {index}/{len(chosen)}")
            if index % 5 == 0:
                write_json(output / "progress.json", {
                    "stage": "vieneu", "completed": index, "target": len(chosen),
                    "accepted": len(voices), "rejected": len(rejected),
                })

    en_count = sum(voice["language"] == "en" for voice in voices)
    vi_count = sum(voice["language"] == "vi" for voice in voices)
    expected_en = piper_expected + kokoro_expected + (vieneu_expected if args.language in ("all", "en") else 0)
    expected_vi = vieneu_expected if args.language in ("all", "vi") else 0
    minimum_en = expected_en if args.limit else max(760, math.ceil(expected_en * 0.85))
    minimum_vi = expected_vi if args.limit else max(20, math.ceil(expected_vi * 0.80))
    if args.language in ("all", "en") and en_count < minimum_en:
        raise RuntimeError(f"English voice acceptance gate failed: {en_count}/{expected_en} < {minimum_en}")
    if args.language in ("all", "vi") and vi_count < minimum_vi:
        raise RuntimeError(f"Vietnamese voice acceptance gate failed: {vi_count}/{expected_vi} < {minimum_vi}")
    if not voices:
        raise RuntimeError("No valid voices were generated")

    archives = {}
    for language in ("en", "vi"):
        if args.language != "all" and language != args.language:
            continue
        archive_path = output / f"voice-library-{language}.zip"
        deterministic_zip(audio_root, language, archive_path, voices)
        archives[language] = {
            "file": archive_path.name,
            "sha256": sha256_file(archive_path),
            "bytes": archive_path.stat().st_size,
            "url": f"https://github.com/Nolane-x/VoiceStudio/releases/download/voice-library-latest/{archive_path.name}",
            "voice_count": sum(voice["language"] == language for voice in voices),
        }

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    manifest = {
        "schema_version": 1,
        "library": "Nolane English and Vietnamese Voice Library",
        "built_at": now,
        "release_tag": "voice-library-latest",
        "counts": {
            "en": en_count,
            "vi": vi_count,
            "total_language_variants": len(voices),
            "unique_voice_identities": len({voice["voice_identity_id"] for voice in voices}),
            "rejected": len(rejected),
            "expected_en": expected_en,
            "expected_vi": expected_vi,
        },
        "source_revisions": source_revisions,
        "archives": archives,
        "quality_policy": QUALITY,
        "quality_disclaimer": (
            "Signal checks and watermark verification are machine checks; they "
            "do not replace a human listening evaluation or a MOS/speaker-similarity study."
        ),
        "voices": sorted(voices, key=lambda voice: (voice["language"], voice["id"])),
        "rejected": len(rejected),
    }
    write_json(output / "manifest.json", manifest)
    write_json(output / "rejected-voices.json", {"count": len(rejected), "items": rejected})
    (output / "build-summary.txt").write_text(
        "\n".join([
            "Nolane English and Vietnamese Voice Library",
            f"Built: {now}",
            f"English voices: {en_count}",
            f"Vietnamese voices: {vi_count}",
            f"Language variants: {len(voices)}",
            f"Unique identities: {manifest['counts']['unique_voice_identities']}",
            f"Rejected: {len(rejected)}",
            "Every published sample passed signal checks and VoiceStudio watermark verification.",
            "",
        ]),
        encoding="utf-8",
    )
    (output / "progress.json").unlink(missing_ok=True)
    log(
        f"BUILD COMPLETE: EN={en_count}, VI={vi_count}, "
        f"unique identities={manifest['counts']['unique_voice_identities']}, "
        f"rejected={len(rejected)}"
    )
    for lang, item in archives.items():
        log(f"{lang.upper()} ZIP: {item['bytes']} bytes SHA256={item['sha256']}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate source/manifest contracts without loading models")
    parser.add_argument("--language", choices=("all", "en", "vi"), default="all")
    parser.add_argument("--limit", type=int, default=0, help="small bounded smoke run; 0 means every eligible voice")
    parser.add_argument("--output", default="dist/voice-library")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be zero or a positive integer")
    return args


def main() -> int:
    args = parse_args()
    if args.check:
        check_static_contract()
        return 0
    check_static_contract()
    return build(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log("cancelled")
        raise SystemExit(130)
    except Exception as exc:
        log(f"FATAL: {type(exc).__name__}: {exc}")
        raise
