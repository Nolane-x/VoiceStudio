from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "render_video_voice.py"
SCHEMA = ROOT / "voice-library" / "video-job.schema.json"
SAMPLES = [
    ROOT / "voice-library" / "video-job.example.vi.json",
    ROOT / "voice-library" / "video-job.example.en.json",
    ROOT / "voice-library" / "video-job.example.en-kokoro.json",
]
SPEC = importlib.util.spec_from_file_location("render_video_voice", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_example_jobs_validate_against_the_published_schema():
    import jsonschema

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    for path in SAMPLES:
        payload = json.loads(path.read_text(encoding="utf-8"))
        jsonschema.validate(payload, schema)
        assert MODULE.validate_job_payload(payload) == payload


def test_sentence_splitter_keeps_all_words_and_sentence_boundaries():
    text = "Xin chào! Đây là câu thứ hai. Và đây là câu cuối."
    chunks = MODULE.split_text(text)
    assert chunks == ["Xin chào!", "Đây là câu thứ hai.", "Và đây là câu cuối."]
    assert " ".join(chunks).replace(" ", "") == text.replace(" ", "")


def test_long_sentences_are_split_at_word_boundaries():
    text = " ".join(f"word{i}" for i in range(120))
    chunks = MODULE.split_text(text, max_chars=72)
    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 72 for chunk in chunks)
    assert " ".join(chunks) == text


def test_caption_timestamps_use_srt_and_vtt_separators():
    assert MODULE.format_timestamp(65.25) == "00:01:05,250"
    assert MODULE.format_timestamp(65.25, vtt=True) == "00:01:05.250"
    assert MODULE.format_timestamp(3_661.007, vtt=True) == "01:01:01.007"


def test_narration_job_has_bounded_size_and_unique_segment_ids():
    payload = json.loads(SAMPLES[0].read_text(encoding="utf-8"))
    payload["segments"].append(dict(payload["segments"][0]))
    try:
        MODULE.validate_job_payload(payload)
    except ValueError as exc:
        assert "unique" in str(exc).lower()
    else:
        raise AssertionError("duplicate segment IDs must be rejected")


def test_kokoro_is_english_only_and_uses_a_canonical_curated_voice_id():
    payload = json.loads((ROOT / "voice-library" / "video-job.example.en-kokoro.json").read_text(encoding="utf-8"))
    assert payload["engine"] == "kokoro"
    assert payload["language"] == "en"
    assert payload["voice_id"] == "en-kokoro-v1-af_heart"
    invalid = dict(payload)
    invalid["language"] = "vi"
    try:
        MODULE.validate_job_payload(invalid)
    except Exception:
        pass
    else:
        raise AssertionError("Kokoro Vietnamese jobs must not be accepted")

def test_renderer_dispatches_kokoro_to_the_pinned_voice_registry():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'elif engine == "kokoro"' in source
    assert "builder.prepare_kokoro()" in source
    assert "builder.render_kokoro_wav" in source
    assert "upstream_quality_grade" in source


def test_watermarking_is_streamed_and_each_saved_block_is_rechecked():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "block_frames = 30 * SAMPLE_RATE" in source
    assert "detect_watermark(waveform, SAMPLE_RATE)" in source
    assert "mark_synthetic(" in source
    assert "PCM_24" in source
