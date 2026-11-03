# KorvaTTS inference-step throughput sweep

## Goal

Measure how the number of flow-matching iterations changes CPU throughput on
GitHub-hosted runners, without assuming that fewer steps preserve audio quality.

## Matrix

- Ten bundled Vietnamese voice styles
- 8, 16, 24 and 32 flow-matching steps
- Same Vietnamese passage, speed and deterministic seed per voice across all
  four step counts
- 40 total samples
- ONNX Runtime CPU only; no hosted TTS service or paid API

The pipeline normalizes all outputs to mono 48 kHz PCM-24, embeds and verifies
VoiceStudio AudioSeal provenance, validates signal integrity, and records
SHA-256, synthesis time, RTFx, RMS, near-silence ratio, peak level and peak RSS.

## Interpretation

This is a speed/technical-signal experiment, not an audio-quality grade.
A lower step count can be faster while degrading tones, consonants, rhythm or
long-form prosody. A blank blind-review CSV is emitted for native Vietnamese
listeners to score all samples before choosing any production inference
setting.

No model weights or original speaker recordings are published. These ten
bundled presets are not new speaker identities. Model/data and bundled
voice-source rights remain a separate promotion gate.

The CPU workflow runs only on the dedicated experiment branch and does not
alter the production library or release workflow.


## First measured run — 2 November 2026

GitHub Actions run 41448537871 completed with 40 / 40 samples generated.

- Model revision: e5c8c218e93c1d8daa53bfe0e62b8fbc5a5e991d
- Package: korvatts==0.1.3
- Ubuntu 24.04, ONNX Runtime CPU, four-thread cap
- Model load: 1.502 seconds
- Peak process RSS: 1,491.6 MiB
- Total speech: 294.612 seconds
- Total synthesis: 175.004 seconds
- All WAVs passed the configured finite-signal, clipping, normalization and
  AudioSeal checks; the blind review sheet is empty and awaiting listeners.

| Flow-matching steps | 10-sample synthesis time | Audio / compute | Compute / audio |
|---:|---:|---:|---:|
| 8 | 19.965 s | 3.693x | 0.271x |
| 16 | 35.784 s | 2.057x | 0.486x |
| 24 | 51.852 s | 1.420x | 0.704x |
| 32 | 67.405 s | 1.092x | 0.915x |

Relative to 32 steps, 8 steps ran about 3.38x faster and 16 steps about 1.88x
faster on this runner. Aggregate RMS and peak levels were very similar across
step counts, but these signal-level statistics do not establish Vietnamese
tone accuracy, consonant clarity, rhythm, prosody or naturalness. Do not
promote 8 or 16 steps to production until blind native-listener comparisons
are scored.

Current result: 8 and 16 steps are throughput candidates; 24 steps are a
middle option; 32 steps remain the upstream quality-oriented baseline.
The production library continues to use its existing configurations until
human listening and rights review are complete.

Artifact: GitHub Actions run 41448537871, artifact
korvatts-step-sweep-41448537871. It contains 40 anonymous WAV samples,
analysis/benchmark.json and a blank blind-review/human-review.csv.
