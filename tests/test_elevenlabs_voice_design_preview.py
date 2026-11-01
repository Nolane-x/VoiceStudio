from __future__ import annotations

import base64
import importlib.util
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "elevenlabs_voice_design_preview.py"
WORKFLOW = ROOT / ".github" / "workflows" / "elevenlabs-voice-design-preview.yml"
SPEC = importlib.util.spec_from_file_location("elevenlabs_voice_design_preview", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _profile():
    return {
        "profile_id": "vi-north-hanoi-0001",
        "language": "vi",
        "locale": "vi-VN",
        "accent_id": "north-hanoi",
        "identity_class": "original_synthetic_persona",
        "voice_description": "Create an original synthetic adult Vietnamese narrator with a natural Northern Hanoi accent, precise tones, warm timbre and measured pacing. Do not imitate any real person.",
        "preview_text": "Xin chào, hôm nay chúng ta sẽ cùng khám phá một câu chuyện mới. Năm 2026, công nghệ thay đổi rất nhanh, nhưng một giọng đọc tốt vẫn cần phát âm đủ sáu thanh điệu và ngắt nghỉ tự nhiên.",
        "seed": 123456,
    }


def test_paid_calls_require_explicit_confirmation_and_api_key():
    args = type("Args", (), {
        "confirm_paid_api_usage": False,
        "profiles": "unused",
        "language": "vi",
        "offset": 0,
        "limit": 1,
        "model_id": "eleven_multilingual_ttv_v2",
        "output": "unused",
    })()
    try:
        MODULE.run(args)
    except ValueError as exc:
        assert "Paid preview calls are blocked" in str(exc)
    else:
        raise AssertionError("Paid API calls must be blocked by default")


def test_design_request_uses_supported_model_and_original_profile_constraints():
    body = MODULE.build_request_body(_profile(), "eleven_multilingual_ttv_v2")
    assert body["seed"] == 123456
    assert body["stream_previews"] is False
    assert body["auto_generate_text"] is False
    assert "Do not imitate" in body["voice_description"]
    assert body["text"].startswith("Xin chào")
    try:
        MODULE.build_request_body(_profile(), "not-a-model")
    except ValueError:
        pass
    else:
        raise AssertionError("Unsupported model IDs must be rejected")


def test_selection_sorts_then_applies_offset_and_limit(tmp_path):
    path = tmp_path / "profiles.jsonl"
    rows = [
        {**_profile(), "profile_id": "vi-z-0002"},
        {**_profile(), "profile_id": "vi-a-0001"},
        {**_profile(), "profile_id": "en-us-0001", "language": "en"},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    selected = MODULE.load_profiles(path, "vi", 1, 1)
    assert [row["profile_id"] for row in selected] == ["vi-z-0002"]


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_design_request_uses_api_key_header_and_returns_preview_metadata():
    payload = {
        "previews": [{
            "generated_voice_id": "generated-test-id",
            "audio_base_64": base64.b64encode(b"fake-audio" * 200).decode(),
            "duration_secs": 2.0,
            "media_type": "audio/mpeg",
        }]
    }
    captured = {}

    def fake_open(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = {key.lower(): value for key, value in request.header_items()}
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse(payload)

    result = MODULE.request_design(
        _profile(),
        "eleven_multilingual_ttv_v2",
        "not-a-real-secret",
        opener=fake_open,
    )
    assert captured["url"] == MODULE.DESIGN_URL
    assert captured["headers"]["x-xi-api-key"] == "not-a-real-secret"
    assert captured["body"]["seed"] == 123456
    assert result["previews"][0]["generated_voice_id"] == "generated-test-id"


def test_public_repository_cannot_publish_provider_design_previews():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.repository.private == true" in source
    assert "github.event.repository.private != true" in source
    assert "confirm_paid_api_usage" in source
    assert "secrets.ELEVENLABS_API_KEY" in source


def test_blind_archive_excludes_profile_and_provider_mapping(tmp_path):
    audio_dir = tmp_path / "blind-audio"
    audio_dir.mkdir(parents=True)
    (audio_dir / "candidate-001.mp3").write_bytes(b"fake-mp3-audio-payload" * 100)
    rows = [{
        "blind_sample_id": "candidate-001",
        "language": "vi",
        "audio_file": "blind-audio/candidate-001.mp3",
    }]
    archive = MODULE.write_blind_review(tmp_path, rows)
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert "index.html" in names
        assert "human-review.csv" in names
        assert "blind-audio/candidate-001.mp3" in names
        assert not any("analysis" in name or "profile" in name or "mapping" in name for name in names)
        page = bundle.read("index.html").decode("utf-8")
        assert "vi-north-hanoi-0001" not in page
        assert "generated_voice_id" not in page
