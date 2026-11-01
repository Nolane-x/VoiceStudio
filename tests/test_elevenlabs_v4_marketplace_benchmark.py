from __future__ import annotations

import importlib.util
import urllib.error
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_elevenlabs_v4_marketplace.py"
SPEC = importlib.util.spec_from_file_location("elevenlabs_v4_marketplace_benchmark", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_payload_uses_eleven_v4_text_to_dialogue_and_explicit_language():
    payload = MODULE.request_payload("vi", "AbCdEf0123456789")
    assert payload["model_id"] == "eleven_v4"
    assert payload["language_code"] == "vi"
    assert payload["apply_text_normalization"] == "auto"
    assert len(payload["inputs"]) == 4
    assert all(item["voice_id"] == "AbCdEf0123456789" for item in payload["inputs"])
    assert sum(len(item["text"]) for item in payload["inputs"]) <= 1800


def test_payload_rejects_unsupported_languages_and_malformed_voice_ids():
    try:
        MODULE.request_payload("fr", "AbCdEf0123456789")
    except ValueError as exc:
        assert "Unsupported language" in str(exc)
    else:
        raise AssertionError("unsupported language was accepted")
    try:
        MODULE.request_payload("en", "bad id")
    except ValueError as exc:
        assert "voice_id" in str(exc)
    else:
        raise AssertionError("malformed voice ID was accepted")


def test_request_is_single_post_and_does_not_leak_api_key(monkeypatch):
    calls = []

    class Response:
        headers = {"Content-Type": "audio/mpeg"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"ID3" + (b"x" * 3000)

    def fake_urlopen(request, timeout):
        calls.append(request)
        return Response()

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fake_urlopen)
    payload = MODULE.generate_dialogue("secret-key", "en", "AbCdEf0123456789")
    assert len(payload) > 2048
    assert len(calls) == 1
    assert calls[0].get_method() == "POST"
    assert calls[0].get_header("Xi-api-key") == "secret-key"
    assert b'"model_id": "eleven_v4"' in calls[0].data


def test_ambiguous_network_failure_is_not_retried(monkeypatch):
    calls = []

    def fail_once(request, timeout):
        calls.append(request)
        raise urllib.error.URLError("connection reset")

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fail_once)
    try:
        MODULE.generate_dialogue("secret-key", "vi", "AbCdEf0123456789")
    except RuntimeError as exc:
        assert "ambiguous" in str(exc)
    else:
        raise AssertionError("network failure should fail closed")
    assert len(calls) == 1


def test_paid_generation_requires_explicit_confirmation_before_any_request():
    args = SimpleNamespace(confirm_paid_api_usage=False)
    try:
        MODULE.run(args)
    except RuntimeError as exc:
        assert "Paid generation blocked" in str(exc)
    else:
        raise AssertionError("paid generation ran without confirmation")


def test_blind_package_contains_no_voice_ids_or_analysis_mapping(tmp_path):
    (tmp_path / "blind-samples").mkdir()
    (tmp_path / "blind-samples" / "sample-001.wav").write_bytes(b"fake wav")
    (tmp_path / "blind-review.html").write_text("<h1>Sample 001</h1>", encoding="utf-8")
    (tmp_path / "blind-review.csv").write_text("blind_sample_id,overall\nsample-001,\n", encoding="utf-8")
    (tmp_path / "BLIND-REVIEW.md").write_text("Blind review only", encoding="utf-8")
    (tmp_path / "analysis.json").write_text('{"voice_id":"SECRETVOICE"}', encoding="utf-8")
    archive = MODULE.create_blind_archive(tmp_path)
    import zipfile
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert "blind-review.html" in names
        assert "blind-samples/sample-001.wav" in names
        assert "analysis.json" not in names
        assert all("SECRETVOICE" not in name for name in names)


def test_blind_html_does_not_expose_marketplace_identity():
    row = {
        "blind_sample_id": "sample-001",
        "language": "vi",
        "audio_file": "blind-samples/sample-001.wav",
        "reference_text_html": "<p>Xin chào.</p>",
    }
    page = MODULE.make_blind_gallery([row], ["vi"], "2026-11-01T00:00:00+00:00")
    assert "Sample 001" in page
    assert "voice_id" not in page
    assert "usage_character_count" not in page
    assert "voice_name" not in page
    assert 'data-sample-id="sample-001"' in page
    assert "card.dataset.sampleId" in page
    assert "reviewer_id" in page
