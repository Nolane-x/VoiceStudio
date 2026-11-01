# Video AI voice-generation contract

This file is the operating guide for an AI agent producing narration for the
Nolane video repository. Use the GitHub Actions TTS service, not a local
VoiceStudio desktop/Electron build.

## Required production flow

1. Read the current `voice-library-latest` release manifest:
   `https://github.com/Nolane-x/VoiceStudio/releases/download/voice-library-latest/manifest.json`.
2. Select a canonical `voice_id` whose `language` matches the narration.
   Keep one speaker identity for a continuous narrator unless the video
   explicitly needs different speakers.
3. For Vietnamese, prefer VieNeu presets: its upstream model card documents
   preset consent and permits commercial use of generated audio. For English,
   select from Kokoro's curated A/A-/B- presets or VieNeu bilingual presets.
   Kokoro's grades are subjective upstream labels, not independent MOS tests;
   Apache-2.0 applies to model/voice assets, not personal endorsement. Piper
   LibriTTS High remains an English-only option with restricted/uncleared
   commercial evidence; do not silently treat it as commercially cleared.
4. Prepare a JSON payload conforming to
   [video-job.schema.json](video-job.schema.json). Use the examples as valid
   starting points. Put each scene, paragraph or subtitle-sized passage in an
   ordered `segments` entry. Preserve punctuation and spelling; do not add
   stage directions that should not be spoken.
5. Invoke the reusable workflow from the video repository. Download the
   `video-voice-assets-<run_id>` artifact from that same Actions run.
6. Listen to `narration.wav` before final publication. Use
   `captions.srt` or `captions.vtt` for subtitle placement and
   `manifest.json` for timing and provenance.

## Reusable workflow call

The video repository can expose a manual input for the JSON payload and call:

```yaml
jobs:
  voiceover:
    uses: Nolane-x/VoiceStudio/.github/workflows/voice-library.yml@main
    with:
      downstream_call: true
      job_json: ${{ inputs.job_json }}
```

The called job checks out the VoiceStudio source itself, so the video
repository does not need to copy the TTS engine or watermark code. It runs on
GitHub-hosted Linux CPU runners; no desktop build, self-hosted GPU or model
API key is required.

## Voice-job JSON

Required fields:

- `schema_version`: `1`
- `language`: `en` or `vi`
- `engine`: `vieneu`, `kokoro` (English only) or `piper` (English only)
- `voice_id`: exact language-specific ID from the current release manifest
- `segments`: ordered objects with unique `id`, `text` and optional
  `pause_ms_after` (0–3000 ms)

Optional fields include `job_id` and `title`. Piper jobs additionally
require `acknowledge_piper_restrictions: true`, which is an explicit
acknowledgment of the source rights limitation, not a grant of commercial
permission.

Single-job safety limits are 30,000 narration characters, 180 rendered
chunks and two hours of final audio. Long text is split at sentence and word
boundaries; narration is not silently truncated.

## Output contract and quality gates

The workflow returns:

- `narration.wav`: mono 48 kHz PCM-24 master for video editing
- `captions.srt`, `captions.vtt`: cues aligned to measured rendered chunk durations
- `transcript.txt`: normalized narration text
- `manifest.json`: selected voice, model revisions, timings, SHA-256,
  mastering targets and watermark results
- `video-voice-assets.zip`: bundled copy

The master target is -18 LUFS integrated loudness and -1.5 dBTP true-peak
ceiling. VoiceStudio AudioSeal marking and detection are performed in
bounded 30-second blocks after mastering; every saved block must pass
post-write detection. The output is then streamed through format, finite
sample, RMS and clipping checks. The build fails closed if these gates fail.

These machine gates do not measure pronunciation accuracy, emotional fit,
naturalness or MOS. A human listening pass is still required before a video
is published. Do not claim a voice is a real person, and do not use
anonymous speaker IDs to infer anyone's identity.
