# KorvaTTS local CPU evaluation

## Purpose

Evaluate KorvaTTS as a possible fast Vietnamese ONNX/CPU engine for
VoiceStudio. This benchmark is separate from the production voice-library
builder and does not add the ten upstream voice styles to a published pack.

## Upstream facts checked on 2 November 2026

- Repository: https://github.com/dogenthq/KorvaTTS
- Model: https://huggingface.co/dogenthq/KorvaTTS
- Package: korvatts==0.1.3
- Inference: ONNX Runtime CPU, 99M-parameter flow-matching architecture.
- Native output: 44.1 kHz.
- Upstream roster: ten bundled styles (five female and five male).
- The authors say Vietnamese is the primary language. English works, but
  quality is not guaranteed to match original Supertonic English voices.
- The model license file says code, weights, and bundled voice styles are Apache-2.0.

## Dataset and voice-source rights warning

The upstream README says training used a filtered subset of
PhoAudiobook (https://huggingface.co/datasets/thivux/phoaudiobook) and a
private Vietnamese/English code-switching set. PhoAudiobook's gated user
agreement restricts use of that dataset to research or education, prohibits
redistribution of the dataset or any part of it, and requires citation when it
is used for published results.

A model publisher's Apache-2.0 declaration is a separate license statement;
it does not, by itself, settle every question about the training dataset,
bundled speaker recordings, or source-voice permissions. Accordingly:

- This benchmark may download the published model and generate private
  evaluation samples.
- It does not upload original raw speaker recordings or model weights.
- Do not treat benchmark output as production-cleared voice assets.
- Keep distribution/promotion blocked until the model publisher's data
  provenance and speaker/source-voice permissions have been reviewed.

References:
- https://huggingface.co/datasets/thivux/phoaudiobook
- https://huggingface.co/dogenthq/KorvaTTS
- https://github.com/dogenthq/KorvaTTS/blob/main/MODEL_LICENSE.md

## Benchmark design

- Pin the model to an immutable Hugging Face commit SHA at runtime.
- Install the pinned PyPI package with CPU ONNX Runtime.
- Synthesize one Vietnamese passage with each of the ten bundled voice styles.
- Probe English and Vietnamese/English code-switching with two styles only.
  These are diagnostic samples, not ten English voices or a guarantee of
  English quality.
- Render at native 44.1 kHz, then normalize with VoiceStudio's standard
  FFmpeg path to mono 48 kHz PCM-24.
- Embed and verify the VoiceStudio AudioSeal provenance watermark.
- Record synthesis time, RTFx, model load time, peak RSS, hashes, and
  per-file technical checks.
- Provide anonymous listening audio and an unfilled human-review CSV.

## Promotion criteria

A technically successful run is not a quality verdict. Native Vietnamese
listeners must review tones, regional accent, consonants, numbers, names,
prosody, long-form continuity, naturalness, and distinctiveness. English
probes must be assessed separately before making English quality claims.
Model/data rights and source-voice permissions must also be reviewed.

The expensive benchmark is manually triggered with
korvatts_benchmark=true in the Voice Library workflow. Ordinary pull requests
run static contracts and smoke checks only; they do not start this CPU
synthesis benchmark.


## Measured GitHub-hosted CPU baseline — 2 November 2026

First successful benchmark run: GitHub Actions run 41445415735.

- Immutable model revision: e5c8c218e93c1d8daa53bfe0e62b8fbc5a5e991d
- Python package: korvatts==0.1.3
- Device: ONNX Runtime CPU, four-thread limit
- Model load: 1.488 seconds
- Peak process RSS: 1,517 MiB
- Main Vietnamese preset matrix: 10 / 10 samples generated
- Extra diagnostics: 2 Vietnamese/English code-switch probes and 2 plain-English probes
- Total: 14 samples, 99.611 seconds of audio, 91.465 seconds of synthesis
- Speed factor (audio duration / synthesis time): 1.089x overall; 1.095x for the ten primary Vietnamese presets
- Conventional real-time factor (synthesis time / audio duration): 0.918 overall
- AudioSeal: 14 / 14 verified, confidence 1.0 in the benchmark report
- PCM validation: 14 / 14 mono, 48 kHz, PCM-24; no clipping

This shows that the engine is light on memory and can run slightly faster than
real time on this hosted CPU. It is not yet a high-throughput mass-rendering
engine: one minute of speech requires about 55 seconds of synthesis, before
accounting for orchestration and quality review. The English results are only
two diagnostic probes and do not establish broad English quality.

The ten bundled presets remain the only source identities in this benchmark.
The extra diagnostic rows are not new voices. No human listening scores have
been entered, and training-data / speaker-source rights remain unresolved.
The artifact contains blind listening samples and an empty review CSV; it
does not contain model weights or original source recordings.

Artifact: GitHub Actions run 41445415735, artifact korvatts-local-cpu-41445415735.
