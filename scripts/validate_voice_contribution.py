#!/usr/bin/env python3
"""Validate pseudonymous voice contribution manifests and production gates.

Signed consent documents, identity verification and raw audio must remain in
private storage. Only opaque references and non-identifying metadata belong in
the public repository.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "voice-library" / "voice-contribution.schema.json"


def custom_errors(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    consent_raw = manifest.get("consent", {})
    consent = consent_raw if isinstance(consent_raw, dict) else {}
    granted_raw = consent.get("rights_granted", [])
    denied_raw = consent.get("rights_not_granted", [])
    granted = {value for value in granted_raw if isinstance(value, str)} if isinstance(granted_raw, list) else set()
    denied = {value for value in denied_raw if isinstance(value, str)} if isinstance(denied_raw, list) else set()
    conflicts = sorted(granted & denied)
    if conflicts:
        errors.append(f"rights cannot be both granted and denied: {', '.join(conflicts)}")

    review_raw = manifest.get("rights_review", {})
    quality_raw = manifest.get("quality_review", {})
    review = review_raw if isinstance(review_raw, dict) else {}
    quality = quality_raw if isinstance(quality_raw, dict) else {}
    if review.get("status") == "approved":
        if not review.get("reviewer_ref") or not review.get("reviewed_at"):
            errors.append("approved rights_review requires reviewer_ref and reviewed_at")
    if quality.get("status") == "approved":
        if not quality.get("blind_review_id") or not quality.get("reviewed_at"):
            errors.append("approved quality_review requires blind_review_id and reviewed_at")
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


def schema_errors(value: Any, rule: dict[str, Any], location: str = "$") -> list[str]:
    """Validate the JSON Schema keywords used by voice-contribution.schema.json.

    Keeping this small validator in the standard library avoids silently relying
    on an unpinned transitive jsonschema dependency in Actions.
    """
    errors: list[str] = []
    expected = rule.get("type")
    type_matches = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "boolean": lambda item: isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
    }
    if expected in type_matches and not type_matches[expected](value):
        return [f"{location}: expected {expected}, got {type(value).__name__}"]

    if "const" in rule and value != rule["const"]:
        errors.append(f"{location}: expected constant {rule['const']!r}")
    if "enum" in rule and value not in rule["enum"]:
        errors.append(f"{location}: value {value!r} is not one of the allowed values")

    if isinstance(value, str):
        if len(value) < rule.get("minLength", 0):
            errors.append(f"{location}: string is shorter than minLength")
        if len(value) > rule.get("maxLength", float("inf")):
            errors.append(f"{location}: string is longer than maxLength")
        pattern = rule.get("pattern")
        if pattern and re.search(pattern, value) is None:
            errors.append(f"{location}: string does not match required pattern")
        fmt = rule.get("format")
        if fmt == "uuid":
            try:
                uuid.UUID(value)
            except (ValueError, AttributeError, TypeError):
                errors.append(f"{location}: value is not a valid UUID")
        elif fmt == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("timezone required")
            except (ValueError, TypeError):
                errors.append(f"{location}: value is not an RFC3339 date-time")
        return errors

    if isinstance(value, list):
        if len(value) < rule.get("minItems", 0):
            errors.append(f"{location}: array has fewer than minItems")
        if len(value) > rule.get("maxItems", float("inf")):
            errors.append(f"{location}: array exceeds maxItems")
        if rule.get("uniqueItems") is True:
            encoded = [
                json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                for item in value
            ]
            if len(encoded) != len(set(encoded)):
                errors.append(f"{location}: array items must be unique")
        item_rule = rule.get("items")
        if isinstance(item_rule, dict):
            for index, item in enumerate(value):
                errors.extend(schema_errors(item, item_rule, f"{location}[{index}]"))
        return errors

    if isinstance(value, dict):
        required = rule.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{location}: missing required property {key!r}")
        properties = rule.get("properties", {})
        if rule.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                errors.append(f"{location}: additional properties are not allowed: {', '.join(extras)}")
        for key, child_rule in properties.items():
            if key in value and isinstance(child_rule, dict):
                errors.extend(schema_errors(value[key], child_rule, f"{location}.{key}"))
    return errors


def validate_manifest(path: Path, schema: dict[str, Any]) -> list[str]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{path}: cannot read JSON: {exc}"]
    if not isinstance(manifest, dict):
        return [f"{path}: manifest root must be an object"]

    issues = [f"{path}: schema: {issue}" for issue in schema_errors(manifest, schema)]
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
