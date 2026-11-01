from __future__ import annotations

import base64
import importlib.util
import json
import urllib.error
import io
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_gemini_tts_prebuilt_voices.py"
SPEC = importlib.util.spec_from_file_location("gemini_tts_prebuilt_benchmark", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def wav_bytes(frame_count: int = 2048, value: int = 0):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(24_000)
        sample = int(value).to_bytes(2, "little", signed=True)
        writer.writeframes(sample * frame_count)
    return buffer.getvalue()


def test_request_uses_supported_gemini_interactions_tts_contract():
    payload = MODULE.build_request("gemini-3.8-flash-tts", "Kore", "vi")
    assert payload["model"] == "gemini-3.8-flash-tts"
    assert payload["response_format"] == {"type": "audio"}
    assert payload["generation_config"]["speech_config"] == [{"voice": "Kore"}]
    content = payload["input"][0]["content"]
    assert len(content) == 4
    assert all(item["annotations"][0]["type"] == "speech_metadata" for item in content)
    assert all(item["type"] == "text" for item in content)
    assert sum(len(item["text"]) for item in content) <= MODULE.MAX_REQUEST_CHARACTERS


def test_request_rejects_unknown_model_language_and_invalid_voice_id():
    for args in [
        ("gemini-old-model", "Kore", "vi"),
        ("gemini-3.8-flash-tts", "Kore", "fr"),
        ("gemini-3.8-flash-tts", "voice with spaces", "en"),
    ]:
        try:
            MODULE.build_request(*args)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid request arguments were accepted: {args}")


def test_extract_audio_supports_interactions_steps_response():
    encoded = base64.b64encode(wav_bytes()).decode("ascii")
    audio = MODULE.extract_audio_bytes({
        "steps": [{
            "type": "model_output",
            "content": [{"type": "audio", "mime_type": "audio/wav", "data": encoded}],
        }]
    })
    assert audio[:4] == b"RIFF"
    assert audio[8:12] == b"WAVE"


def test_extract_audio_concatenates_all_distinct_wav_blocks_in_order():
    first = wav_bytes(frame_count=1500, value=111)
    second = wav_bytes(frame_count=2200, value=222)
    encoded_first = base64.b64encode(first).decode("ascii")
    encoded_second = base64.b64encode(second).decode("ascii")
    # API may repeat output_audio data in steps; duplicate copies are deduped.
    result = MODULE.extract_audio_bytes({
        "output_audio": {"data": encoded_first},
        "steps": [{
            "content": [
                {"type": "audio", "data": encoded_first},
                {"type": "audio", "data": encoded_second},
            ]
        }],
    })
    with wave.open(io.BytesIO(result), "rb") as merged:
        assert merged.getframerate() == 24_000
        assert merged.getnchannels() == 1
        assert merged.getnframes() == 1500 + 2200


def test_extract_audio_rejects_incompatible_wav_segments_instead_of_dropping_one():
    first = wav_bytes(frame_count=1500)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16_000)
        writer.writeframes(b"\\x00\\x00" * 1600)
    encoded = [
        base64.b64encode(first).decode("ascii"),
        base64.b64encode(buffer.getvalue()).decode("ascii"),
    ]
    try:
        MODULE.extract_audio_bytes({
            "steps": [{"content": [{"type": "audio", "data": item} for item in encoded]}]
        })
    except RuntimeError as exc:
        assert "incompatible WAV formats" in str(exc)
    else:
        raise AssertionError("incompatible WAV segments were silently mixed")


def test_extract_audio_rejects_missing_or_non_wav_output():
    try:
        MODULE.extract_audio_bytes({"steps": [{"content": [{"type": "text", "data": "hello"}]}]})
    except RuntimeError as exc:
        assert "complete WAV" in str(exc)
    else:
        raise AssertionError("text-only response was accepted")

    encoded = base64.b64encode(b"not-wav" * 500).decode("ascii")
    try:
        MODULE.extract_audio_bytes({"output_audio": {"data": encoded}})
    except RuntimeError as exc:
        assert "complete WAV" in str(exc)
    else:
        raise AssertionError("non-WAV bytes were accepted")


def test_generate_speech_posts_once_and_extracts_audio(monkeypatch):
    calls = []

    class Response:
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            encoded = base64.b64encode(wav_bytes()).decode("ascii")
            return json.dumps({
                "steps": [{
                    "type": "model_output",
                    "content": [{"type": "audio", "data": encoded}],
                }]
            }).encode("utf-8")

    def fake_urlopen(request, timeout):
        calls.append(request)
        return Response()

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fake_urlopen)
    audio = MODULE.generate_speech("test-api-key", "gemini-3.8-flash-tts", "Kore", "en")
    assert audio[:4] == b"RIFF"
    assert len(calls) == 1
    assert calls[0].get_method() == "POST"
    assert calls[0].get_header("X-goog-api-key") == "test-api-key"
    body = json.loads(calls[0].data.decode("utf-8"))
    assert body["model"] == "gemini-3.8-flash-tts"


def test_ambiguous_network_failure_is_not_retried(monkeypatch):
    calls = []

    def fail_once(request, timeout):
        calls.append(request)
        raise urllib.error.URLError("connection reset after request")

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fail_once)
    try:
        MODULE.generate_speech("test-api-key", "gemini-3.8-flash-tts", "Kore", "vi")
    except RuntimeError as exc:
        assert "ambiguous" in str(exc)
    else:
        raise AssertionError("ambiguous provider request should fail closed")
    assert len(calls) == 1


def test_catalog_load_only_accepts_valid_and_prebuilt_voice_rows(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({
        "source": "test-catalog",
        "voices": [
            {"voice_id": "Kore", "display_name": "Kore", "archetype": "firm"},
            {"voice_id": "Kore", "display_name": "duplicate"},
            {"voice_id": "prompted-1", "type": "prompted"},
            {"voice_id": "bad id", "type": "prebuilt"},
            {"voice_id": "Kore-VI", "type": "prebuilt", "languages": ["vi-VN"]},
        ],
    }), encoding="utf-8")
    rows = MODULE.load_voice_catalog(path)
    assert [row["voice_id"] for row in rows] == ["Kore", "Kore-VI"]
    assert rows[0]["source"] == "test-catalog"
    assert MODULE.select_voices(rows, "vi", 0, 4) == rows
    assert MODULE.select_voices(rows, "en", 0, 4) == rows[:1]


def test_blind_gallery_hides_voice_identity_and_exports_stable_sample_id():
    row = {
        "blind_sample_id": "sample-001",
        "language": "vi",
        "audio_file": "blind-samples/sample-001.wav",
        "reference_text_html": "<p>Xin chào.</p>",
    }
    page = MODULE.make_blind_gallery([row], "gemini-3.8-flash-tts", "2026-11-01T00:00:00+00:00")
    assert "Sample 001" in page
    assert "voice_id" not in page
    assert "Kore" not in page
    assert 'data-sample-id="sample-001"' in page
    assert "card.dataset.sampleId" in page
    assert "reviewer_id" in page


def test_paid_generation_is_blocked_without_confirmation():
    from types import SimpleNamespace

    args = SimpleNamespace(confirm_paid_api_usage=False)
    try:
        MODULE.run(args)
    except RuntimeError as exc:
        assert "Paid Gemini generation blocked" in str(exc)
    else:
        raise AssertionError("paid Gemini TTS request was not gated")


def test_blind_archive_does_not_include_private_analysis_mapping(tmp_path):
    import zipfile

    (tmp_path / "blind-samples").mkdir()
    (tmp_path / "blind-samples" / "sample-001.wav").write_bytes(wav_bytes())
    (tmp_path / "blind-review.html").write_text("Sample 001", encoding="utf-8")
    (tmp_path / "blind-review.csv").write_text("blind_sample_id,overall\nsample-001,\n", encoding="utf-8")
    (tmp_path / "BLIND-REVIEW.md").write_text("Blind only", encoding="utf-8")
    (tmp_path / "analysis.json").write_text('{"voice_id":"PRIVATEVOICE"}', encoding="utf-8")
    archive = MODULE.create_blind_archive(tmp_path)
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert "analysis.json" not in names
        assert "blind-samples/sample-001.wav" in names
        assert all("PRIVATEVOICE" not in name for name in names)
