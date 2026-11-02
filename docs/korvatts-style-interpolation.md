# KorvaTTS interpolated speaker-style experiment

## Question

Can interpolation between the ten bundled KorvaTTS speaker-style tensor pairs
create additional stable, natural-sounding Vietnamese timbres without
retraining the model or using reference-audio cloning?

The upstream VoiceStyle contract stores two tensors:
- style_ttl: (1, 50, 256)
- style_dp: (1, 8, 16)

The inference API accepts either a preset name or a VoiceStyle object. This
experiment therefore constructs convex combinations of both tensors and
passes each resulting object directly to the local ONNX CPU synthesizer.

## Experimental matrix

Five same-gender source pairs are selected. For each pair, the second speaker's
weight is 0.25, 0.50, or 0.75, giving 15 candidate blends. Each sample reads
the same Vietnamese text, is rendered at 44.1 kHz, normalized to mono 48 kHz
PCM-24, watermarked with VoiceStudio AudioSeal, and technically validated.

The analysis artifact records:
- immutable model revision
- both source styles and interpolation weights
- cosine similarity in the concatenated style-embedding space
- per-sample synthesis time, RTFx, waveform checks and SHA-256

Embedding cosine similarity is only a numerical diagnostic. It is not a
speaker-verification metric or evidence of human-perceived distinctness.

## Non-promotion rules

This is an experiment in timbre blending, not a claim that 15 new independent
speaker identities have been created. A valid waveform can still sound like
an unnatural, ambiguous, or nearly identical blend. Human native-Vietnamese
listeners must score naturalness, tones, prosody, pronunciation, and
distinctness before any candidate is considered further.

The KorvaTTS model publisher labels the model and voice styles Apache-2.0, but
its README says training used a filtered PhoAudiobook subset and a private
code-switching corpus. Training-data provenance and bundled voice-source
permissions remain a separate rights gate. No model weights or original
speaker recordings are uploaded in this workflow.

The workflow runs only when commits are pushed to the dedicated experiment
branch. It does not touch the production voice-library build or release.


## First measured CPU run — 2 November 2026

GitHub Actions run 41447080039 completed successfully on Ubuntu 24.04.

- Model revision: e5c8c218e93c1d8daa53bfe0e62b8fbc5a5e991d
- Package: korvatts==0.1.3
- Model load: 1.615 seconds
- Peak process RSS: 1,398.8 MiB
- Candidate matrix: 15 planned, 15 generated, 0 failed/collapsed
- Total generated speech: 111.242 seconds
- Total synthesis compute: 104.915 seconds
- Overall speed factor (audio / compute): 1.0603x
- Every candidate passed the current audio format, clipping, finite-signal,
  normalization and AudioSeal verification checks.
- The anonymous listening CSV is still blank; human review is not complete.

### What the embedding measurements say

Across the 15 interpolated samples, cosine similarity between the mixed
embedding and its source A averaged 0.9554; similarity to source B averaged
0.9598. Individual values ranged from 0.9013 to 0.9935 for source A and
0.9082 to 0.9935 for source B.

This is a useful warning: all mixtures remain numerically close to both
source preset embeddings. It does not prove that the WAVs sound identical,
but it also does not support a claim that they are 15 clearly distinct
speaker identities. Cosine similarity in this concatenated tensor space is
not a speaker-verification or perceptual-distance metric.

The candidates are therefore experimental timbre blends only. They must not
be added to the production voice count or distributed as independent
identities until blind native-Vietnamese listening demonstrates naturalness
and stable perceptual distinction, and the model/data/source-voice rights
review is complete.

Artifact: GitHub Actions run 41447080039, artifact
korvatts-style-mix-41447080039. The artifact contains 15 blind samples and
an empty human-review CSV; the mapping and similarity data are in
analysis/benchmark.json.
