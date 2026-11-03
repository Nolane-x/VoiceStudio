# OmniVoice Vietnamese CPU reference-cloning evaluation

## Purpose

Screen OmniVoice as a possible local path for turning consented Vietnamese
reference recordings into reusable voice prompts. The first run deliberately
uses two synthetic KorvaTTS reference clips, so it tests the technical
reference-audio cloning path without using any real person's voice.

## Upstream source and checkpoint provenance

- Source repository: https://github.com/k2-fsa/OmniVoice
- Pinned source commit: 08be0b4ccbac3e13e374e86fbfead4b4cac343e2
- Upstream code repository license: Apache-2.0
- Hugging Face model: https://huggingface.co/k2-fsa/OmniVoice
- Hugging Face audio tokenizer: https://huggingface.co/eustlb/higgs-audio-v2-tokenizer
- The current model-weight and audio-tokenizer repository metadata does not
  declare a license. This screen does not redistribute weights and must not
  be treated as approval for commercial use or distribution.

The upstream repository supports 600+ language IDs including Vietnamese
(vi). It supports reference-audio voice cloning and reusable VoiceClonePrompt
objects. Its README recommends a 3–10 second reference clip. The upstream
voice-design mode is primarily trained on Chinese and English, so this
Vietnamese screen uses same-language Vietnamese reference-audio cloning.

## Test design

- Resolve immutable Hugging Face commit revisions for OmniVoice and its
  Higgs Audio V2 tokenizer.
- Materialize the pinned snapshots into a local CPU inference directory.
- Use PyTorch CPU, float32 and SDPA attention; no CUDA device is used.
- Resolve an immutable KorvaTTS model commit, then generate two short Vietnamese reference clips locally with KorvaTTS 0.1.3:
  bao_kim and gia_bao. Their exact spoken text is known.
- Encode each synthetic reference once as a reusable VoiceClonePrompt.
- Generate two Vietnamese target passages per prompt, four outputs total,
  using 32 decoding steps.
- Measure model load, prompt-encoding time, generation time, output duration,
  peak resident memory, and per-clip real-time factor.
- Normalize output to mono 48 kHz PCM-24, verify VoiceStudio AudioSeal
  provenance and run signal validation.
- Upload only anonymous cloned outputs and a blank human-review CSV. The
  synthetic reference WAVs and the reference-to-prompt mapping are not in the
  blind-review folder.

## Rights and identity boundaries

The two test references are synthetic KorvaTTS preset outputs, not human
recordings and not contributor identities. The generated outputs are an
engineering clone-path test, not new production-approved voices.

Real contributor voice cloning requires explicit, documented consent for the
reference recording, synthesis, retention, distribution and commercial use.
The upstream source repository's Apache-2.0 code license does not resolve the
separate license status of the model checkpoint, audio-tokenizer weights or
the training/source recordings. Production promotion remains blocked until
those rights are clarified and native Vietnamese listeners complete blind
review.

No hosted TTS endpoint, external voice-cloning service or paid provider is
used. No checkpoint weights or original reference audio are uploaded into
VoiceStudio artifacts.
