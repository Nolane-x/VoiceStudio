from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "voice-library" / "gemini-prebuilt-studio-voices.json"
WORKFLOW = ROOT / ".github" / "workflows" / "gemini-tts-prebuilt-benchmark.yml"
SCRIPT = ROOT / "scripts" / "benchmark_gemini_tts_prebuilt_voices.py"


def test_official_gemini_prebuilt_catalog_has_30_unique_documented_options():
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    voices = data["voices"]
    ids = [voice["voice_id"] for voice in voices]
    assert data["count"] == 30
    assert len(ids) == 30
    assert len(set(ids)) == 30
    assert "Zephyr" in ids
    assert "Kore" in ids
    assert "Sulafat" in ids
    assert data["source"] == "https://ai.google.dev/gemini-api/docs/speech-generation"
    assert all(voice["source"].startswith("Google-published") for voice in voices)


def test_gemini_paid_benchmark_has_private_and_manual_confirmation_gates():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    assert "github.event.repository.private == true" in workflow
    assert "inputs.confirm_paid_api_usage == true" in workflow
    assert "default: false" in workflow
    assert "MAX_TOTAL_REQUESTS = 8" in script
    assert "if not args.confirm_paid_api_usage" in script
    assert "No retry" in script
    assert "GEMINI_API_KEY" in workflow


def test_gemini_benchmark_compares_flash_and_flash_lite_separately():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "gemini-3.8-flash-tts" in workflow
    assert "gemini-3.8-flash-lite-tts" in workflow
    assert "run once per model for a fair comparison" in workflow
