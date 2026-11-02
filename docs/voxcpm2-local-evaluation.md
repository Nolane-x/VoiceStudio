# Local VoxCPM2 CPU evaluation

## Scope

This workflow evaluates the open openbmb/VoxCPM2 checkpoint on a CPU-only
GitHub Actions runner. It downloads model weights from Hugging Face, resolves
an immutable commit SHA for the run, and loads the local snapshot with CPU
inference and torch.compile disabled. No hosted TTS endpoint, provider key or
paid synthesis service is used.

The Python package is pinned to version 2.0.3. Upstream declares Apache-2.0.
This does not automatically clear every upstream training dataset, speaker
recording, voice identity or intended downstream use; those require separate
review.

## First screening matrix

- Two original, non-imitative synthetic voice designs.
- Each design rendered in Vietnamese and English.
- Two utterances per identity/language, reusing a deterministic seed.
- Eight generated samples total, at the model's native 48 kHz output.
- Mono PCM-24 loudness normalization, VoiceStudio AudioSeal watermark and
  saved-file verification.
- Anonymous listening audio is separated from the prompt/identity mapping.

## Promotion rules

A generated WAV is not automatically a production-ready voice identity.
The first run only checks CPU feasibility and technical audio integrity.
Promotion requires blind native-language review for pronunciation, Vietnamese
tones, proper names, numbers, accent fit, naturalness, prosody and long-form
continuity, plus upstream rights review. Named-person imitation is out of scope
unless that speaker has explicitly authorized it.

## Why this is not yet a thousand-voice build

VoxCPM2 is a 2B-parameter model. CPU inference is supported upstream, but
GitHub Actions throughput and peak memory must be measured before deciding
whether large-scale generation is practical. This first run deliberately
limits scope to two designed identities. A positive result can justify
resumable, bounded voice-design batches and comparisons with other eligible
local models.

## Reproduction and artifacts

The workflow runs on pull requests touching the evaluation files or can be
started manually. It installs CPU-only PyTorch and downloads the open model.

- Blind-review artifact: anonymous audio gallery plus a blank human-review CSV.
- Analysis artifact: prompts, identity mapping, immutable model revision,
  timings, hashes, audio checks and watermark evidence.

The job does not emit human-preference rankings or production approval.
