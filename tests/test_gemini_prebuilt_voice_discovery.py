from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "discover_gemini_prebuilt_voices.py"
SPEC = importlib.util.spec_from_file_location("gemini_prebuilt_voice_discovery", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def prebuilt(voice_id, name, language_code, voice_type="prebuilt", **extra):
    return {
        "id": voice_id,
        "display_name": name,
        "type": voice_type,
        "model": "gemini-3.8-flash-tts",
        "language_code": language_code,
        "region_code": "VN" if language_code.startswith("vi") else "US",
        "accent": "Northern Vietnamese" if language_code.startswith("vi") else "American",
        "persona": "Warm narrator",
        "context": "Audiobook",
        "gender": "Female",
        "pitch": "Medium",
        **extra,
    }


def test_normalize_only_accepts_prebuilt_vietnamese_and_english_voices():
    vi = MODULE.normalize_voice(prebuilt("Kore", "Kore", "vi-VN"))
    en = MODULE.normalize_voice(prebuilt("Aoede", "Aoede", "en-US"))
    assert vi is not None and vi["language"] == "vi"
    assert vi["language_code"] == "vi-VN"
    assert en is not None and en["language"] == "en"
    assert MODULE.normalize_voice(prebuilt("custom", "Custom", "vi-VN", "prompted")) is None
    assert MODULE.normalize_voice(prebuilt("replica", "Replica", "en-US", "replicated")) is None
    assert MODULE.normalize_voice(prebuilt("zh-voice", "Chinese", "zh-CN")) is None


def test_catalog_follows_page_tokens_deduplicates_and_reports_language_counts():
    calls = []

    def fake_fetcher(api_key, page_token):
        calls.append(page_token)
        if page_token is None:
            return {
                "voices": [
                    prebuilt("Kore", "Kore", "vi-VN"),
                    prebuilt("Aoede", "Aoede", "en-US"),
                    prebuilt("Kore", "Kore duplicate", "vi-VN"),
                    prebuilt("Private", "Prompted", "vi-VN", "prompted"),
                ],
                "next_page_token": "next-1",
            }
        return {
            "voices": [
                prebuilt("Leda", "Leda", "vi-VN"),
                prebuilt("Orus", "Orus", "en-GB"),
            ]
        }

    voices, report = MODULE.collect_catalog("test-key", 3, fetcher=fake_fetcher)
    assert calls == [None, "next-1"]
    assert {voice["voice_id"] for voice in voices} == {"Kore", "Aoede", "Leda", "Orus"}
    assert report["pages_fetched"] == 2
    assert report["unique_prebuilt_voices"] == 4
    assert report["language_counts"] == {"vi": 2, "en": 2}
    assert not report["has_more_after_page_cap"]


def test_catalog_reports_pagination_cap_without_claiming_complete_inventory():
    def fake_fetcher(api_key, page_token):
        return {"voices": [prebuilt("Kore", "Kore", "vi-VN")], "next_page_token": "still-more"}

    voices, report = MODULE.collect_catalog("test-key", 2, fetcher=fake_fetcher)
    assert len(voices) == 1
    assert report["pages_fetched"] == 2
    assert report["has_more_after_page_cap"]


def test_page_limit_is_bounded():
    for value in (0, 11, -1):
        try:
            MODULE.collect_catalog("test-key", value, fetcher=lambda *_: {"voices": []})
        except ValueError as exc:
            assert "max_pages" in str(exc)
        else:
            raise AssertionError(f"Invalid page cap {value} was accepted")


def test_list_voices_request_uses_prebuilt_filter_and_pagination(monkeypatch):
    captured = {}

    def fake_request_json(url, api_key):
        captured["url"] = url
        captured["api_key"] = api_key
        return {"voices": []}

    monkeypatch.setattr(MODULE, "request_json", fake_request_json)
    MODULE.list_prebuilt_voices("api-secret", "token-123")
    assert captured["api_key"] == "api-secret"
    assert captured["url"].startswith(MODULE.API_URL + "?")
    assert "page_size=1000" in captured["url"]
    assert "type=prebuilt" in captured["url"]
    assert "page_token=token-123" in captured["url"]


def test_writer_receives_only_normalized_catalog_data_and_never_serializes_api_key(tmp_path):
    import inspect

    parameters = inspect.signature(MODULE.write_catalog).parameters
    assert list(parameters) == ["output", "voices", "report"]
    voice = MODULE.normalize_voice(prebuilt("Kore", "Kore", "vi-VN"))
    assert voice is not None
    report = {
        "pages_fetched": 1,
        "page_size": MODULE.PAGE_SIZE,
        "max_pages": 1,
        "has_more_after_page_cap": False,
        "unique_prebuilt_voices": 1,
        "language_counts": {"vi": 1, "en": 0},
    }
    catalog = MODULE.write_catalog(tmp_path, [voice], report)
    encoded = (tmp_path / "catalog.json").read_text(encoding="utf-8")
    assert catalog["voices"][0]["voice_id"] == "Kore"
    assert "Kore" in encoded
    assert "api_key" not in encoded.casefold()
    assert "GEMINI_API_KEY" not in encoded


def test_html_catalog_escapes_untrusted_provider_metadata():
    voice = MODULE.normalize_voice(prebuilt(
        "Kore", "<script>alert(1)</script>", "vi-VN",
        description="<img src=x onerror=alert(1)>",
    ))
    assert voice is not None
    page = MODULE.make_html([voice], "2026-11-01T00:00:00+00:00")
    assert "&lt;script&gt;" in page
    assert "&lt;img" in page
    assert "<script>alert(1)</script>" not in page
    assert "prompted" not in page
