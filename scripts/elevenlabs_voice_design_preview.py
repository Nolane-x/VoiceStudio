#!/usr/bin/env python3
"""Create a small, explicitly paid ElevenLabs Voice Design preview batch.

This script only creates preview candidates. It does not create persistent
provider voices, clone a real person, or publish into a public voice library.
"""
from __future__ import annotations

import argparse
import base64
import csv
import html
import json
import os
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

DESIGN_URL = "https://api.elevenlabs.io/v1/text-to-voice/design"
ALLOWED_MODELS = {"eleven_multilingual_ttv_v2", "eleven_ttv_v3"}
MODEL_LANGUAGES = {
    "eleven_multilingual_ttv_v2": frozenset({"en"}),
    "eleven_ttv_v3": frozenset({"en", "vi"}),
}
AUTO_MODEL_BY_LANGUAGE = {
    "en": "eleven_multilingual_ttv_v2",
    "vi": "eleven_ttv_v3",
}
MAX_BATCH = 8


def load_profiles(path: Path, language: str, offset: int, limit: int) -> list[dict[str, Any]]:
    if offset < 0:
        raise ValueError("offset must be zero or greater")
    if not 1 <= limit <= MAX_BATCH:
        raise ValueError(f"limit must be between 1 and {MAX_BATCH}")
    rows = []
    allowed_languages = {"vi", "en"} if language == "both" else {language}
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at line {line_no}: {exc}") from exc
            if row.get("language") in allowed_languages:
                rows.append(row)
    rows.sort(key=lambda row: row["profile_id"])
    selected = rows[offset:offset + limit]
    if not selected:
        raise ValueError("No profiles selected; check language, offset and catalog size")
    return selected


def resolve_model_id(profile: dict[str, Any], requested_model_id: str = "auto") -> str:
    """Resolve a provider model per language and reject unsupported language/model pairs."""
    language = str(profile.get("language", "")).strip().lower()
    if language not in AUTO_MODEL_BY_LANGUAGE:
        raise ValueError(f"Unsupported Voice Design language: {language!r}")

    if requested_model_id == "auto":
        model_id = str(profile.get("model_id_default") or AUTO_MODEL_BY_LANGUAGE[language])
        if language not in MODEL_LANGUAGES.get(model_id, frozenset()):
            # Older profile catalogs assigned multilingual-v2 to every language.
            # Correct stale Vietnamese defaults rather than sending unsupported text.
            model_id = AUTO_MODEL_BY_LANGUAGE[language]
    else:
        model_id = requested_model_id

    if model_id not in ALLOWED_MODELS:
        raise ValueError(f"Unsupported ElevenLabs model: {model_id}")
    if language not in MODEL_LANGUAGES[model_id]:
        raise ValueError(
            f"ElevenLabs model {model_id} does not support language {language}; "
            f"supported languages for this workflow: {', '.join(sorted(MODEL_LANGUAGES[model_id]))}"
        )
    return model_id


def build_request_body(profile: dict[str, Any], model_id: str = "auto") -> dict[str, Any]:
    model_id = resolve_model_id(profile, model_id)
    description = profile.get("voice_description", "")
    text = profile.get("preview_text", "")
    if not 20 <= len(description) <= 1000:
        raise ValueError("voice_description must contain 20-1000 characters")
    if not 100 <= len(text) <= 1000:
        raise ValueError("preview_text must contain 100-1000 characters")
    if profile.get("identity_class") != "original_synthetic_persona":
        raise ValueError("Only original synthetic persona profiles may be previewed")
    return {
        "voice_description": description,
        "model_id": model_id,
        "text": text,
        "auto_generate_text": False,
        "seed": int(profile["seed"]),
        "guidance_scale": 5.0,
        "loudness": 0.5,
        "stream_previews": False,
        "should_enhance": False,
    }


def request_design(
    profile: dict[str, Any],
    model_id: str,
    api_key: str,
    *,
    timeout: int = 120,
    opener=urllib.request.urlopen,
) -> dict[str, Any]:
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY is required for paid preview generation")
    body = json.dumps(build_request_body(profile, model_id)).encode("utf-8")
    request = urllib.request.Request(
        DESIGN_URL,
        data=body,
        headers={"Content-Type": "application/json", "xi-api-key": api_key},
        method="POST",
    )
    for attempt in range(3):
        try:
            with opener(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            previews = result.get("previews")
            if not isinstance(previews, list) or not previews:
                raise RuntimeError("ElevenLabs returned no voice previews")
            if len(previews) > 3:
                raise RuntimeError(f"Unexpected preview count: {len(previews)}")
            for item in previews:
                if not item.get("generated_voice_id") or not item.get("audio_base_64"):
                    raise RuntimeError("Preview response is missing generated_voice_id or audio")
            return result
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", "replace")[:500]
            if attempt < 2 and (exc.code == 429 or 500 <= exc.code <= 599):
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"ElevenLabs Voice Design HTTP {exc.code}: {message}") from exc
        except urllib.error.URLError as exc:
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"ElevenLabs Voice Design network failure: {exc.reason}") from exc
    raise RuntimeError("ElevenLabs Voice Design failed after retries")


def write_blind_review(output: Path, rows: list[dict[str, Any]]) -> Path:
    cards = []
    for row in rows:
        fields = ("naturalness", "pronunciation", "accent_fit", "prosody", "distinctiveness", "overall")
        ratings = "".join(
            f'<label>{field.replace("_", " ").title()}'
            f'<input type="number" min="1" max="5" data-field="{field}"></label>'
            for field in fields
        )
        cards.append(
            '<article class="sample">'
            f'<div class="meta">{html.escape(row["blind_sample_id"])} · {html.escape(row["language"].upper())}</div>'
            f'<h2>Preview {html.escape(row["blind_sample_id"])}</h2>'
            f'<audio controls preload="none" src="{html.escape(row["audio_file"], quote=True)}"></audio>'
            f'<div class="ratings">{ratings}</div>'
            '<label><input type="checkbox" data-field="approve"> Approve this candidate for persistent account voice creation</label>'
            '<label>Notes<textarea data-field="notes" rows="2"></textarea></label></article>'
        )
    page = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Blind Synthetic Voice Design Review</title>
<style>
body{max-width:1100px;margin:30px auto;padding:0 18px;font:15px/1.55 system-ui,sans-serif}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.sample{border:1px solid #8888;border-radius:12px;padding:14px}audio{width:100%}
.ratings{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
label{display:block;font-size:.86rem}input,textarea{box-sizing:border-box;width:100%;padding:7px;margin:4px 0 8px}
.meta{opacity:.7;font-size:.75rem}button{padding:9px 14px}
</style></head><body><h1>Blind voice-design preview review</h1>
<p>These are synthetic design previews. Rate only what you hear. No profile description, seed, generated voice ID or design prompt is included in this package.</p>
<button id="export">Export scores CSV</button><div class="grid">""" + "".join(cards) + """</div>
<script>
document.getElementById('export').addEventListener('click',()=>{
 const fields=['naturalness','pronunciation','accent_fit','prosody','distinctiveness','overall','notes'];
 const rows=[['blind_sample_id','language','approve',...fields]];
 document.querySelectorAll('.sample').forEach(card=>rows.push([
  card.querySelector('.meta').textContent.split(' · ')[0],
  card.querySelector('.meta').textContent.split(' · ')[1],
  card.querySelector('[data-field="approve"]').checked ? 'yes' : 'no',
  ...fields.map(field=>card.querySelector('[data-field="'+field+'"]').value)
 ]));
 const csv=rows.map(row=>row.map(value=>'"'+String(value??'').replaceAll('"','""')+'"').join(',')).join('\n');
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download='voice-design-human-review.csv';a.click();
});
</script></body></html>"""
    output.mkdir(parents=True, exist_ok=True)
    page_path = output / "index.html"
    page_path.write_text(page, encoding="utf-8")
    csv_path = output / "human-review.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["blind_sample_id", "language", "approve", "naturalness", "pronunciation", "accent_fit", "prosody", "distinctiveness", "overall", "notes"])
        for row in rows:
            writer.writerow([row["blind_sample_id"], row["language"], "no", "", "", "", "", "", "", ""])
    readme = output / "BLIND-REVIEW.md"
    readme.write_text(
        "# Blind Voice Design Review\n\n"
        "This package contains only synthetic preview audio, blind IDs, and a blank review form. "
        "It does not contain source prompts, profile IDs, seeds, provider-generated voice IDs, "
        "or model mapping. These are provider-account previews and must not be represented as "
        "publicly shareable marketplace voices.\n",
        encoding="utf-8",
    )
    archive = output / "blind-review.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4) as bundle:
        allowed = [page_path, csv_path, readme] + sorted((output / "blind-audio").glob("*.mp3"))
        for path in allowed:
            bundle.write(path, path.relative_to(output).as_posix())
    return archive


def run(args: argparse.Namespace) -> int:
    if not args.confirm_paid_api_usage:
        raise ValueError("Paid preview calls are blocked. Pass --confirm-paid-api-usage only after approving provider usage.")
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise ValueError("Set ELEVENLABS_API_KEY in GitHub Actions secrets before dispatching this paid workflow")

    profiles = load_profiles(Path(args.profiles), args.language, args.offset, args.limit)
    output = Path(args.output)
    blind_dir = output / "blind-audio"
    blind_dir.mkdir(parents=True, exist_ok=True)
    analysis_rows = []
    blind_rows = []
    candidate_index = 0
    model_ids_used: dict[str, int] = {}
    for profile in profiles:
        selected_model_id = resolve_model_id(profile, args.model_id)
        response = request_design(profile, selected_model_id, api_key)
        model_ids_used[selected_model_id] = model_ids_used.get(selected_model_id, 0) + 1
        for preview_index, item in enumerate(response["previews"], start=1):
            candidate_index += 1
            blind_id = f"candidate-{candidate_index:03d}"
            try:
                audio = base64.b64decode(item["audio_base_64"], validate=True)
            except (ValueError, KeyError) as exc:
                raise RuntimeError(f"Invalid base64 preview returned for {blind_id}") from exc
            if len(audio) < 1000 or len(audio) > 20 * 1024 * 1024:
                raise RuntimeError(f"Preview audio size outside safety bounds for {blind_id}: {len(audio)} bytes")
            audio_name = f"{blind_id}.mp3"
            audio_path = blind_dir / audio_name
            audio_path.write_bytes(audio)
            blind_rows.append({
                "blind_sample_id": blind_id,
                "language": profile["language"],
                "audio_file": f"blind-audio/{audio_name}",
            })
            analysis_rows.append({
                "blind_sample_id": blind_id,
                "profile_id": profile["profile_id"],
                "language": profile["language"],
                "locale": profile["locale"],
                "accent_id": profile["accent_id"],
                "intended_use_case": profile.get("intended_use_case"),
                "market_archetype_id": profile.get("market_archetype_id"),
                "market_archetype_label": profile.get("market_archetype_label"),
                "dimensions": profile["dimensions"],
                "voice_description": profile["voice_description"],
                "seed": profile["seed"],
                "model_id": selected_model_id,
                "generated_voice_id": item["generated_voice_id"],
                "duration_seconds": item.get("duration_secs"),
                "media_type": item.get("media_type", "audio/mpeg"),
                "audio_file": f"blind-audio/{audio_name}",
                "generation_state": "preview_generated_not_saved_as_persistent_voice",
                "shareability": "not_shareable_to_public_elevenlabs_voice_library",
            })
        time.sleep(1.0)

    output.mkdir(parents=True, exist_ok=True)
    (output / "analysis.json").write_text(
        json.dumps({
            "schema_version": 1,
            "provider": "ElevenLabs Voice Design",
            "model_selection": "per-profile-language-safe-routing",
            "model_ids_used": model_ids_used,
            "profiles_selected": len(profiles),
            "preview_candidates": len(analysis_rows),
            "persistent_voices_created": 0,
            "paid_api_calls": len(profiles),
            "human_review_required": True,
            "records": analysis_rows,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    archive = write_blind_review(output, blind_rows)
    (output / "README.md").write_text(
        "# ElevenLabs Voice Design Preview Batch\n\n"
        f"- Profiles requested: {len(profiles)}\n"
        f"- Preview variants received: {len(analysis_rows)}\n"
        "- Persistent voices created: 0\n"
        "- Public Voice Library publication: not supported for Voice Design previews\n\n"
        "Share only blind-review.zip with listeners. Keep analysis.json private because it contains "
        "profile-to-provider mapping and generated voice IDs. Select a winning preview only after "
        "human review. Creating persistent voices is a separate step and is intentionally not "
        "performed by this workflow.\n",
        encoding="utf-8",
    )
    print(
        f"Created {len(analysis_rows)} blind previews from {len(profiles)} paid design calls; "
        "persistent voices created=0"
    )
    print(f"Blind review ZIP: {archive}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--language", choices=("vi", "en", "both"), default="both")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument(
        "--model-id",
        choices=("auto", *sorted(ALLOWED_MODELS)),
        default="auto",
        help="auto selects a language-compatible model for each profile",
    )
    parser.add_argument("--output", default="dist/elevenlabs-voice-design")
    parser.add_argument("--confirm-paid-api-usage", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= MAX_BATCH:
        parser.error(f"--limit must be between 1 and {MAX_BATCH}")
    if args.offset < 0:
        parser.error("--offset must be zero or greater")
    return args


def main() -> int:
    try:
        return run(parse_args())
    except Exception as exc:
        print(f"[voice-design] ERROR: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
