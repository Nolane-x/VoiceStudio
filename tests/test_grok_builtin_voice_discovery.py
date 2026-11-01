from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "discover_grok_builtin_voices.py"
SPEC = importlib.util.spec_from_file_location("grok_builtin_voice_discovery", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_normalize_builtin_voice_adds_only_documented_builtin_metadata():
    voice = MODULE.normalize_voice({"voice_id": "CARINA", "name": "Carina", "language": "multilingual"})
    assert voice is not None
    assert voice["voice_id"] == "carina"
    assert voice["language_scope"] == ["vi", "en"]
    assert voice["tone"] == "soft, empathetic, soothing"
    assert "wellness" in voice["use_cases"]


def test_language_specific_voice_only_keeps_supported_track():
    voice = MODULE.normalize_voice({"voice_id": "narrator", "name": "Narrator", "language": "vi"})
    assert voice is not None
    assert voice["language_scope"] == ["vi"]
    assert MODULE.normalize_voice({"voice_id": "other", "name": "Other", "language": "fr"}) is None


def test_catalog_reads_provider_builtin_list_endpoint_and_deduplicates():
    calls = []

    def fake_fetcher(url, api_key):
        calls.append((url, api_key))
        return {
            "voices": [
                {"voice_id": "eve", "name": "Eve", "language": "multilingual"},
                {"voice_id": "ara", "name": "Ara", "language": "multilingual"},
                {"voice_id": "eve", "name": "Duplicate Eve", "language": "multilingual"},
            ]
        }

    voices = MODULE.collect_catalog("test-key", fetcher=fake_fetcher)
    assert calls == [(MODULE.API_URL, "test-key")]
    assert [voice["voice_id"] for voice in voices] == ["ara", "eve"]
    assert MODULE.API_URL.endswith("/v1/tts/voices")
    assert "/v1/custom-voices" not in MODULE.API_URL


def test_http_request_uses_bearer_auth_and_builtin_only_endpoint(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"voices":[{"voice_id":"eve","name":"Eve","language":"multilingual"}]}'

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        return Response()

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fake_urlopen)
    result = MODULE.request_json(MODULE.API_URL, "secret")
    assert captured["url"] == MODULE.API_URL
    assert captured["auth"] == "Bearer secret"
    assert result["voices"][0]["voice_id"] == "eve"


def test_gallery_escapes_untrusted_provider_metadata():
    voice = MODULE.normalize_voice({
        "voice_id": "eve",
        "name": "<script>alert(1)</script>",
        "language": "multilingual",
    })
    page = MODULE.make_html([voice], "2026-11-01T00:00:00+00:00")
    assert "&lt;script&gt;" in page
    assert "<script>alert(1)</script>" not in page
    assert "No audio was generated" in page
