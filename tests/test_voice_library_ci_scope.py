from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCOPE_PATH = ROOT / ".github" / "scripts" / "ci_scope.py"
SPEC = importlib.util.spec_from_file_location("voice_library_ci_scope", SCOPE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_voice_library_service_changes_do_not_trigger_desktop_runtime_ci():
    paths = [
        "voice-library/sources.json",
        "voice-library/manifest.schema.json",
        "voice-jobs/example.json",
        "scripts/build_voice_library.py",
        "scripts/render_video_voice.py",
        ".github/workflows/voice-library.yml",
    ]
    assert all(MODULE.non_runtime(path) for path in paths)


def test_shared_ci_classifier_changes_trigger_runtime_ci():
    assert not MODULE.non_runtime(".github/scripts/ci_scope.py")


def test_actual_app_runtime_changes_still_trigger_runtime_ci():
    paths = [
        "backend/services/watermark.py",
        "backend/api/routers/tts.py",
        "electron/src/main/index.ts",
        "pyproject.toml",
    ]
    assert all(not MODULE.non_runtime(path) for path in paths)
