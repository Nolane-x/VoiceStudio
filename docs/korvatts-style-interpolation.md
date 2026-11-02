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
