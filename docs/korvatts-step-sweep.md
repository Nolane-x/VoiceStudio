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
