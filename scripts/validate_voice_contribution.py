#!/usr/bin/env python3
"""Validate pseudonymous voice contribution manifests and production gates.

Signed consent documents, identity verification and raw audio must remain in
private storage. Only opaque references and non-identifying metadata belong in
the public repository.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "voice-library" / "voice-contribution.schema.json"


def custom_errors(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    consent = manifest.get("consent", {})
    granted = set(consent.get("rights_granted", []))
    denied = set(consent.get("rights_not_granted", []))
    conflicts = sorted(granted & denied)
    if conflicts:
        errors.append(f"rights cannot be both granted and denied: {', '.join(conflicts)}")

    review = manifest.get("rights_review", {})
    quality = manifest.get("quality_review", {})
    if quality.get("status") == "approved":
        required_checks = (
            "native_language_review",
            "pronunciation_review",
            "longform_stability_review",
        )
        missing = [field for field in required_checks if quality.get(field) is not True]
        if missing:
            errors.append(
                "quality status cannot be approved until all checks pass: "
                + ", ".join(missing)
            )

    if manifest.get("production_ready") is True:
        required_rights = {"tts_synthesis", "voice_replication", "commercial_use"}
        missing_rights = sorted(required_rights - granted)
        if missing_rights:
            errors.append(
                "production_ready requires explicit consent for: "
                + ", ".join(missing_rights)
            )
        if review.get("status") != "approved":
            errors.append("production_ready requires an approved rights_review")
        if quality.get("status") != "approved":
            errors.append("production_ready requires an approved quality_review")
        if consent.get("disclosure_acknowledged") is not True:
            errors.append("production_ready requires acknowledged synthetic-voice disclosure")

    if "public_preview" in granted and "public_distribution" not in granted:
        errors.append(
            "public_preview requires public_distribution permission for any externally hosted preview asset"
        )
    return errors


def validate_manifest(path: Path, schema: dict[str, Any]) -> list[str]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{path}: cannot read JSON: {exc}"]
    if not isinstance(manifest, dict):
        return [f"{path}: manifest root must be an object"]

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    issues = [
        f"{path}: schema: {issue.message}"
        for issue in sorted(validator.iter_errors(manifest), key=lambda item: list(item.path))
    ]
    issues.extend(f"{path}: policy: {message}" for message in custom_errors(manifest))
    return issues


def collect_paths(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    if not target.is_dir():
        raise FileNotFoundError(f"Contribution manifest path does not exist: {target}")
    return sorted(path for path in target.glob("*.json") if path.name != SCHEMA_PATH.name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=ROOT / "voice-library" / "contributions",
        help="One manifest JSON file or a directory of manifests",
    )
    args = parser.parse_args()
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        manifests = collect_paths(args.path)
    except Exception as exc:
        print(f"[voice-contribution] ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if not manifests:
        print(f"[voice-contribution] No contribution manifests found in {args.path}; nothing to validate.")
        return 0

    all_errors = []
    for path in manifests:
        all_errors.extend(validate_manifest(path, schema))
    if all_errors:
        for error in all_errors:
            print(f"[voice-contribution] ERROR {error}", file=sys.stderr)
        print(
            f"[voice-contribution] FAILED {len(all_errors)} issue(s) across {len(manifests)} manifest(s)",
            file=sys.stderr,
        )
        return 1

    print(f"[voice-contribution] PASS {len(manifests)} pseudonymous manifest(s); no audio or personal data was read.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
