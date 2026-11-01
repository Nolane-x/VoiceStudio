from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_tts_candidates.py"
SPEC = importlib.util.spec_from_file_location("tts_candidate_benchmark", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_vietnamese_normalization_keeps_diacritics():
    assert MODULE.normalize_text("ĐỪNG bỏ cuộc, nhé!") == "đừng bỏ cuộc nhé"


def test_english_error_metrics_are_word_based():
    metrics = MODULE.error_metrics("The quick brown fox.", "the quick fox", "en")
    assert metrics["token_error_rate"] == 0.25
    assert metrics["token_unit"] == "words"
    assert metrics["character_error_rate"] > 0


def test_vietnamese_error_metrics_are_labelled_syllable_not_lexical_word_error():
    metrics = MODULE.error_metrics("Xin chào thế giới.", "Xin chào thế bạn.", "vi")
    assert metrics["token_error_rate"] == 0.25
    assert metrics["token_unit"] == "whitespace-delimited Vietnamese syllables"


def test_vietnamese_reference_scripts_cover_tones_and_number_reading():
    assert "12,6" in MODULE.SCRIPTS["vi"][1][2]
    assert "Đôi khi" in MODULE.SCRIPTS["vi"][0][2]


def test_supertonic_is_not_promoted_to_a_commercial_voice_catalogue():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'revision = constants.PINNED_REVISION_SHA' in source
    assert '"commercial_use": "not-cleared-by-this-benchmark"' in source
    assert '"manual-review-required"' in source


def test_kokoro_and_piper_are_kept_language_scoped():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'if "en" in languages:' in source
    assert '"engine": "kokoro"' in source
    assert '"engine": "piper"' in source


def test_html_gallery_escapes_narration_text_and_has_audio_controls():
    manifest = {"built_at": "2026-11-01T00:00:00+00:00"}
    rows = [{
        "language": "en",
        "engine": "test",
        "engine_label": "Test engine",
        "voice_id": "voice-1",
        "voice_label": "Voice",
        "scenario_title": "Story",
        "audio_file": "samples/test.wav",
        "reference_text": "<script>alert(1)</script>",
        "asr": {"transcript": "A transcript"},
        "asr_metrics": {"token_error_rate": 0.0, "character_error_rate": 0.0},
        "rtfx": 2.0,
    }]
    page = MODULE.make_gallery(rows, manifest)
    assert "<audio controls" in page
    assert "&lt;script&gt;" in page
    assert "<script>alert(1)</script>" not in page
    assert "Export human ratings CSV" in page


def test_supertonic_renderer_captures_its_model_instance_before_vieneu_loads():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "*, _tts=tts, _style=style, _lang=language" in source
    assert "waveform, _ = _tts.synthesize(" in source


def test_piper_benchmark_uses_the_same_supplied_reference_text():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "_voice.synthesize_wav(" in source
    assert "text, wav_file" in source
    assert "builder.render_piper_wav(voice, _id, path)" not in source


def test_benchmark_render_loop_uses_the_declared_script_corpus():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'expected = sum(len(SCRIPTS[c["language"]]) for c in candidates)' in source
    assert 'for scenario_id, scenario_title, reference in SCRIPTS[candidate["language"]]:' in source
    assert "TEXTS" not in source
