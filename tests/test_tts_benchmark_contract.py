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
    assert len(MODULE.SCRIPTS["vi"]) == 4


def test_matched_corpus_covers_conversation_and_long_form_in_both_languages():
    for language in ("en", "vi"):
        scenarios = {row[0] for row in MODULE.SCRIPTS[language]}
        assert scenarios == {"story", "numbers", "conversation", "longform"}
        long_form = next(row[2] for row in MODULE.SCRIPTS[language] if row[0] == "longform")
        assert len(long_form) >= 400



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
    manifest = {"built_at": "2026-11-01T00:00:00+00:00", "languages": ["en"]}
    rows = [{
        "language": "en",
        "engine": "test",
        "engine_label": "Test engine",
        "voice_id": "voice-1",
        "voice_label": "Voice",
        "scenario_id": "story",
        "scenario_title": "Story",
        "blind_sample_id": "sample-001",
        "audio_file": "blind-samples/sample-001.wav",
        "reference_text": "<script>alert(1)</script>",
        "asr": {"transcript": "A transcript"},
        "asr_metrics": {"token_error_rate": 0.0, "character_error_rate": 0.0},
        "rtfx": 2.0,
    }]
    page = MODULE.make_gallery(rows, manifest)
    assert "<audio controls" in page
    assert "&lt;script&gt;" in page
    assert "<script>alert(1)</script>" not in page
    assert "Export listening scores as CSV" in page


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


def test_benchmark_master_format_constants_are_explicit():
    assert MODULE.TARGET_RATE == 48_000
    assert MODULE.TARGET_BITS == 24


def test_listening_gallery_contains_no_model_identity_or_objective_diagnostics():
    manifest = {"built_at": "2026-11-01T00:00:00+00:00", "languages": ["vi"]}
    rows = [{
        "engine": "supertonic",
        "engine_label": "Supertonic 3",
        "voice_id": "F3",
        "voice_label": "Female 3",
        "language": "vi",
        "scenario_id": "story",
        "scenario_title": "Văn kể chuyện",
        "blind_sample_id": "sample-001",
        "audio_file": "blind-samples/sample-001.wav",
        "reference_text": "Đôi khi, một lựa chọn nhỏ.",
        "asr": {"transcript": "Đôi khi một lựa chọn nhỏ"},
        "asr_metrics": {"token_error_rate": 0.0, "character_error_rate": 0.0},
        "rtfx": 4.2,
    }]
    page = MODULE.make_gallery(rows, manifest)
    assert "<audio controls" in page
    assert "Blind voice review" in page
    assert "sample-001" in page
    assert "Đôi khi" in page
    assert "Supertonic" not in page
    assert "Female 3" not in page
    assert "F3" not in page
    assert "Đôi khi một lựa chọn nhỏ" not in page
    assert "RTFx" not in page
    assert "CER" not in page
    assert "Reveal model identities" not in page
    assert "blind-human-review.csv" in page
    assert "blind_sample_id" in page
    assert "reviewer-id" in page
    assert "reviewer_id" in page
    assert "card.dataset.sampleFile" in page


def test_audio_samples_are_moved_to_neutral_blind_filenames(tmp_path):
    source_dir = tmp_path / "samples"
    source_dir.mkdir()
    source = source_dir / "supertonic-F3-vi-story.wav"
    source.write_bytes(b"test-audio-bytes")
    rows = [{
        "language": "vi",
        "scenario_id": "story",
        "audio_file": "samples/supertonic-F3-vi-story.wav",
        "engine": "supertonic",
        "voice_id": "F3",
    }]
    MODULE.anonymize_samples(rows, tmp_path)
    assert rows[0]["blind_sample_id"] == "sample-001"
    assert rows[0]["audio_file"] == "blind-samples/sample-001.wav"
    assert (tmp_path / rows[0]["audio_file"]).read_bytes() == b"test-audio-bytes"
    assert not source.exists()


def test_shareable_blind_archive_excludes_the_engine_mapping(tmp_path):
    import zipfile

    (tmp_path / "index.html").write_text("<html>Blind listening</html>", encoding="utf-8")
    (tmp_path / "human-review.csv").write_text("blind_sample_id,score\\nsample-001,5\\n", encoding="utf-8")
    (tmp_path / "BLIND-REVIEW.md").write_text("Blind review only.", encoding="utf-8")
    (tmp_path / "benchmark.json").write_text('{"engine":"supertonic"}', encoding="utf-8")
    audio_dir = tmp_path / "blind-samples"
    audio_dir.mkdir()
    (audio_dir / "sample-001.wav").write_bytes(b"neutral-audio")
    archive = MODULE.create_blind_review_archive(tmp_path)
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert "index.html" in names
        assert "human-review.csv" in names
        assert "BLIND-REVIEW.md" in names
        assert "blind-samples/sample-001.wav" in names
        assert "benchmark.json" not in names
        assert all("supertonic" not in name.casefold() for name in names)



def test_longform_benchmark_uses_extended_duration_cap_only_for_longform():
    class Builder:
        def __init__(self):
            self.calls = []

        def validate_audio(self, path, sample_rate, bits, *, max_duration_s=None):
            self.calls.append((path, sample_rate, bits, max_duration_s))
            return {"duration_seconds": 53.44}

    builder = Builder()
    longform = MODULE.validate_benchmark_audio(builder, Path("longform.wav"), "longform")
    shortform = MODULE.validate_benchmark_audio(builder, Path("story.wav"), "story")

    assert longform["duration_seconds"] == 53.44
    assert shortform["duration_seconds"] == 53.44
    assert builder.calls[0] == (Path("longform.wav"), 48_000, 24, 75.0)
    assert builder.calls[1] == (Path("story.wav"), 48_000, 24, None)


def test_library_audio_validator_keeps_its_default_duration_cap():
    import inspect

    builder = MODULE.load_builder()
    parameter = inspect.signature(builder.validate_audio).parameters["max_duration_s"]
    assert parameter.default is None
    assert builder.QUALITY["max_duration_s"] == 35.0



def test_benchmark_template_csv_includes_reviewer_identity_column():
    source = SCRIPT.read_text(encoding="utf-8")
    assert '["blind_sample_id", "language", "scenario", "reviewer_id"' in source
    assert "document.getElementById('reviewer-id')" in source


def test_score_merger_is_wired_as_a_standalone_post_review_tool():
    from pathlib import Path

    merger = ROOT / "scripts" / "merge_tts_blind_scores.py"
    assert merger.is_file()
    source = merger.read_text(encoding="utf-8")
    assert "voice_rankings_by_language" in source
    assert "voice_rankings_by_language_and_scenario" in source
    assert '"commercial_use"' in source
