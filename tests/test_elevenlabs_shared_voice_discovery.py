from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "discover_elevenlabs_shared_voices.py"
SPEC = importlib.util.spec_from_file_location("elevenlabs_shared_voice_discovery", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sample_voice(voice_id, name, language, category="high_quality", usage=1000):
    return {
        "voice_id": voice_id,
        "name": name,
        "category": category,
        "language": language,
        "accent": "northern" if language == "vi" else "american",
        "gender": "Female",
        "description": "Warm, clear narration",
        "preview_url": "https://example.com/preview.mp3",
        "usage_character_count_1y": usage,
        "usage_character_count_7d": 100,
        "cloned_by_count": 12,
        "featured": True,
        "verified_languages": [
            {"language": language, "model_id": "eleven_v4", "accent": "american", "locale": "en-US"}
        ],
    }


def test_normalize_voice_preserves_verified_language_and_usage_signals():
    voice = MODULE.normalize_voice(sample_voice("v-en-1", "Studio Voice", "en", usage=12345))
    assert voice is not None
    assert voice["languages"] == ["en"]
    assert voice["verified_languages"][0]["model_id"] == "eleven_v4"
    assert voice["usage_character_count_1y"] == 12345
    assert voice["cloned_by_count"] == 12


def test_famous_category_is_excluded_even_if_returned_by_provider():
    assert MODULE.normalize_voice(
        sample_voice("celebrity-1", "Famous Person", "en", category="famous")
    ) is None


def test_catalog_deduplicates_voices_and_keeps_language_specific_market_signals():
    def fake_fetcher(*, language, category, sort, page, api_key=None):
        if language == "en":
            rows = [sample_voice("shared-en", "English Voice", "en", usage=500)]
        else:
            rows = [sample_voice("shared-vi", "Vietnamese Voice", "vi", usage=900)]
        return {"voices": rows, "has_more": False, "total_count": 73}

    voices, queries = MODULE.collect_catalog(["vi", "en"], 1, fetcher=fake_fetcher)
    by_id = {voice["voice_id"]: voice for voice in voices}

    assert set(by_id) == {"shared-en", "shared-vi"}
    assert len(queries) == 12
    assert all(query["provider_total_count"] == 73 for query in queries)
    assert len(by_id["shared-en"]["discovery_ranks"]) == 6
    assert len(by_id["shared-vi"]["discovery_ranks"]) == 6
    assert by_id["shared-vi"]["usage_character_count_1y"] == 900
    assert by_id["shared-en"]["adoption_signals"]["interpretation"].endswith(
        "not listener quality scores"
    )


def test_catalog_stops_when_provider_has_no_more_pages():
    calls = []

    def fake_fetcher(*, language, category, sort, page, api_key=None):
        calls.append((language, category, sort, page))
        return {"voices": [], "has_more": False}

    _, queries = MODULE.collect_catalog(["vi"], 3, fetcher=fake_fetcher)
    assert len(calls) == 6
    assert all(query["pages_fetched"] == 1 for query in queries)
    assert not any(query["has_more_after_page_cap"] for query in queries)


def test_page_cap_is_reported_when_provider_still_has_more_results():
    def fake_fetcher(*, language, category, sort, page, api_key=None):
        return {"voices": [], "has_more": True}

    _, queries = MODULE.collect_catalog(["en"], 2, fetcher=fake_fetcher)
    assert len(queries) == 6
    assert all(query["pages_fetched"] == 2 for query in queries)
    assert all(query["has_more_after_page_cap"] for query in queries)


def test_marketplace_preview_gallery_escapes_untrusted_text_and_requires_https():
    voice = MODULE.normalize_voice(sample_voice("id-1", "<script>alert(1)</script>", "en"))
    assert voice is not None
    voice["description"] = "<img src=x onerror=alert(1)>"
    page = MODULE.make_html([voice], "2026-11-01T00:00:00+00:00")
    assert "&lt;script&gt;" in page
    assert "&lt;img" in page
    assert "<script>alert(1)</script>" not in page
    assert '<audio controls' in page
    voice["preview_url"] = "javascript:alert(1)"
    safe_page = MODULE.make_html([voice], "2026-11-01T00:00:00+00:00")
    assert "javascript:alert(1)" not in safe_page
    assert "No preview URL supplied." in safe_page


def test_request_uses_documented_shared_voice_filters(monkeypatch):
    captured = {}

    def fake_request_json(url, api_key):
        captured["url"] = url
        captured["api_key"] = api_key
        return {"voices": [], "has_more": False}

    monkeypatch.setattr(MODULE, "_request_json", fake_request_json)
    MODULE.fetch_shared_voices(
        language="vi", category="high_quality", sort="usage_character_count_1y",
        page=2, api_key="test-key",
    )
    assert captured["api_key"] == "test-key"
    assert captured["url"].startswith(MODULE.API_URL + "?")
    for fragment in (
        "language=vi", "category=high_quality", "sort=usage_character_count_1y",
        "page=2", "page_size=100", "include_live_moderated=false",
    ):
        assert fragment in captured["url"]



def test_discovery_report_preserves_provider_total_count():
    def fake_fetcher(*, language, category, sort, page, api_key=None):
        return {"voices": [], "has_more": page == 0, "total_count": 247}

    _, queries = MODULE.collect_catalog(["vi"], 2, fetcher=fake_fetcher)
    assert len(queries) == 6
    assert all(query["provider_total_count"] == 247 for query in queries)
    assert all(query["has_more_after_page_cap"] for query in queries)
