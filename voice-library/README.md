# Nolane English & Vietnamese Voice Library

This directory defines a reproducible voice-library build. It is deliberately
separate from VoiceStudio application features: it does not change the UI,
backend engines, model catalogue, or normal release process.

## Target catalogue

The build creates independent, auditionable WAV previews for:

- **English (US):** the 904 anonymous speaker IDs in Piper's
  `en_US-libritts-high` multi-speaker model. Its per-voice card identifies
  the model quality as **high**, the rate as 22.05 kHz, and the LibriTTS
  `train-clean-360` source dataset as CC BY 4.0.
- **Vietnamese:** every preset returned by the pinned VieNeu-TTS SDK at build
  time. The upstream v3 Turbo model card currently documents 23 presets
  covering North, Central and South, with 48 kHz output. The build records
  the actual runtime list instead of hard-coding a count.
- **English bilingual variants:** the same VieNeu preset identities are also
  auditioned in English, using the model's documented English–Vietnamese
  bilingual capability. They remain labelled as bilingual voices, not as
  native-English speakers.

This yields hundreds of distinct English voice choices plus Vietnamese
presets. The generated manifest distinguishes unique speaker identities from
language-specific voice variants.

## Build and storage

All model inference and audio processing run in GitHub Actions:

1. Download the pinned Piper model and the public VieNeu v3 Turbo assets.
2. Generate one comparable English and Vietnamese audition passage for each
   applicable speaker/preset.
3. Normalize playback loudness and check WAV integrity, finite samples,
   duration, silence, and clipping.
4. Route every generated WAV through VoiceStudio's
   `services.watermark.mark_synthetic(force=True)` chokepoint and verify the
   saved file with `detect_watermark`.
5. Write SHA-256 metadata, rejected-item reports, and separate language ZIPs.
6. Publish the ZIPs and manifest to the rolling
   [voice-library-latest release](https://github.com/Nolane-x/VoiceStudio/releases/tag/voice-library-latest).

Binary audio is kept in release assets rather than Git history. The source
definitions, build script, validation contract and attribution are committed
here. Pull requests run a small real-model smoke build; pushes to main build
the complete library.

## Rights and attribution

### English — Piper / LibriTTS High

The selected per-voice model card identifies 904 speakers, high quality,
22,050 Hz and the LibriTTS `train-clean-360` dataset with CC BY 4.0. The
generated previews retain attribution to LibriTTS and link the upstream
model card and licence. Piper's current project documentation notes that
voice licences vary and describes the engine as intended for personal use
and text-to-speech research. For that reason, this repository records the
source licence and does **not** promise blanket commercial, publicity,
endorsement, or identifiable-speaker rights beyond the published evidence.
Do not map anonymous speaker IDs to real people.

### Vietnamese — VieNeu-TTS v3 Turbo

The upstream model card states that its shipped preset-voice assets are
Apache-2.0, that the speakers or rightsholders granted appropriate consent
for training and synthetic speech, and that audio generated with those
presets may be used commercially. The build uses the public v3 Turbo SDK
and ONNX CPU path in FP32. It records the exact model and codec revisions
resolved during the run. VieNeu v4 is proprietary and is not used.

### Generated audio

All previews are synthetic output, not original recordings. Each WAV is
watermarked through VoiceStudio's provenance function; the build fails
publication if the watermark cannot be detected after saving. The manifest
stores source, model, language, sample text, sample rate, encoding,
watermark status and SHA-256 digest. It makes no claim that an audio sample
is a genuine statement by a real speaker.

See [ATTRIBUTION.md](ATTRIBUTION.md) and [sources.json](sources.json) for
the exact source records.

## Video narration jobs (the production interface)

The library workflow is also a **reusable GitHub Actions TTS service**. A
video-production workflow can call it directly; no Electron app, local model,
desktop service, or API key is required on the video runner.

A job contains a language, engine, canonical voice ID and ordered narration
segments. See the validated contract and examples:

- [Job JSON Schema](video-job.schema.json)
- [Vietnamese example](video-job.example.vi.json)
- [English example](video-job.example.en.json)

The AI should choose a canonical `voice_id` from the generated
`manifest.json`. The VieNeu examples are safe starting references; exact
voice IDs are checked against the pinned preset list at runtime. Piper is
English-only and its rights are not blanket commercially cleared, so a
Piper job is rejected unless `acknowledge_piper_restrictions` is explicitly
set after reviewing the recorded rights warning.

### Call from a downstream video repository

A workflow in the video repository can invoke this public reusable workflow:

```yaml
name: Render video narration
on:
  workflow_dispatch:
    inputs:
      job_json:
        description: Voice job JSON conforming to voice-library/video-job.schema.json
        required: true
        type: string

jobs:
  voiceover:
    uses: Nolane-x/VoiceStudio/.github/workflows/voice-library.yml@main
    with:
      job_json: ${{ inputs.job_json }}
```

The job JSON can be composed by the video AI agent and passed as the
`job_json` input (maximum 65,535 characters). The called workflow downloads
the pinned CPU/ONNX TTS assets, renders narration, applies EBU R128 loudness
mastering, produces a mono 48 kHz PCM-24 master, embeds and re-detects the
VoiceStudio AudioSeal mark in bounded 30-second blocks, and uploads an
artifact to the same Actions run.

The returned artifact contains:

- `narration.wav` — master voiceover ready for video editing
- `captions.srt` and `captions.vtt` — sentence/chunk captions aligned to the rendered audio
- `transcript.txt` — narration text
- `manifest.json` — voice/model revisions, timing, loudness target, watermark verification and SHA-256
- `video-voice-assets.zip` — deterministic bundle of the above

You can also run the workflow directly from the Actions tab on the
VoiceStudio repository: choose `Render video narration`, set `task` to
`render`, and paste the JSON into `job_json`. The default `catalog` task
continues to build and publish the full voice packs.

The renderer splits long passages at sentence/word boundaries without
dropping narration text, preserves requested pauses, emits exact timing
metadata and caps a single job at 30,000 characters / 180 chunks / two hours.
The final audio is checked in a streaming pass for finite samples, RMS,
clipping, 48 kHz mono PCM-24 format and post-save watermark verification.
These are machine checks, not a substitute for listening to the finished
voiceover before publishing a video.
