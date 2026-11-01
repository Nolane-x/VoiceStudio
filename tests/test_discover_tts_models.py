from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "discover_tts_models.py"
SPEC = importlib.util.spec_from_file_location("discover_tts_models", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_discovery_collects_distinct_market_signals_and_merges_duplicate_models():
    calls = []

    def fake_open(request, timeout):
        query = parse_qs(urlparse(request.full_url).query)
        calls.append(query)
        language_filter = query.get("filter", [None])[0]
        rows = [{
            "id": "publisher/vietnamese-tts",
            "downloads": 1200,
            "likes": 80,
            "trendingScore": 8.5,
            "tags": ["text-to-speech", "language:vi", "license:apache-2.0"],
            "pipeline_tag": "text-to-speech",
        }]
        if language_filter is None:
            rows.append({
                "id": "publisher/english-tts",
                "downloads": 900,
                "likes": 35,
                "trendingScore": 5.0,
                "tags": ["text-to-speech", "language:en"],
                "pipeline_tag": "text-to-speech",
            })
        return _FakeResponse(rows)

    result = MODULE.collect_discovery(
        limit=10,
        opener=fake_open,
        now=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    assert result["model_count"] == 2
    assert result["generated_at"] == "2026-11-01T00:00:00+00:00"
    assert len(calls) == len(MODULE.QUERY_PLAN)
    vietnamese = next(row for row in result["models"] if row["model_id"] == "publisher/vietnamese-tts")
    assert vietnamese["signal_ranks"]["vi_trending"] == 1
    assert vietnamese["license"] == "apache-2.0"
    assert vietnamese["discovery_status"] == "discovery_only_not_benchmarked_or_rights_cleared"


def test_discovery_uses_hub_language_filter_and_trending_sort():
    urls = []

    def fake_open(request, timeout):
        urls.append(request.full_url)
        return _FakeResponse([])

    MODULE._request_models("trendingScore", 12, "vi", opener=fake_open)
    query = parse_qs(urlparse(urls[0]).query)
    assert query["pipeline_tag"] == ["text-to-speech"]
    assert query["sort"] == ["trendingScore"]
    assert query["filter"] == ["language:vi"]
    assert query["limit"] == ["12"]
    assert {"downloads", "likes", "tags", "trendingScore", "createdAt", "lastModified"} <= set(query["expand"])


def test_discovery_rejects_invalid_limits_and_does_not_infer_commercial_rights():
    try:
        MODULE.collect_discovery(limit=101)
    except ValueError as exc:
        assert "between 1 and 100" in str(exc)
    else:
        raise AssertionError("Discovery limit must be bounded")

    row = MODULE._normalize({
        "id": "publisher/no-license",
        "downloads": 20,
        "likes": 2,
        "tags": ["text-to-speech"],
    })
    assert row["license"] is None
    assert row["rights_review"] == "required_before_model_download_or_production_use"


def test_report_writes_json_and_human_readable_market_summary(tmp_path):
    payload = {
        "generated_at": "2026-11-01T00:00:00+00:00",
        "model_count": 1,
        "limit_per_query": 5,
        "source_results": [{"source": "all_trending"}],
        "source_errors": [],
        "query_plan": [{"source": "all_trending"}],
        "models": [{
            "model_id": "publisher/model",
            "downloads": 123,
            "likes": 4,
            "trending_score": 2.0,
            "language_tags": ["vi"],
            "license": None,
        }],
    }
    report, readme = MODULE.write_report(payload, tmp_path)
    assert json.loads(report.read_text(encoding="utf-8"))["models"][0]["model_id"] == "publisher/model"
    assert "publisher/model" in readme.read_text(encoding="utf-8")
    assert "not a quality ranking" in readme.read_text(encoding="utf-8")
