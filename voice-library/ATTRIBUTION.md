# Voice Library — attribution and notices

## English: Piper LibriTTS High

- Voice model: `rhasspy/piper-voices`, entry `en_US-libritts-high`.
- Model card: https://huggingface.co/rhasspy/piper-voices/tree/49a0d23f04e055f1766e5ad15ea2d121a90fa17a/en/en_US/libritts/high
- Dataset: LibriTTS `train-clean-360`, CC BY 4.0 as identified by the
  model card.
- Dataset citation: Heiga Zen et al., “LibriTTS: A Corpus Derived from
  LibriSpeech for Text-to-Speech,” Interspeech 2019.
- Attribution: “Generated with the Piper `en_US-libritts-high` model,
  trained on the LibriTTS dataset (CC BY 4.0). Changes: new text-to-speech
  audio generated and loudness-normalized; provenance watermark embedded.”
- Piper runtime: `piper-tts` 1.8.0, GPL-3.0-or-later. The runtime is used
  by the GitHub Actions builder and is not bundled as part of the audio ZIP.

The model card lists the dataset licence, while Piper's documentation
emphasizes that each voice has its own terms. Do not treat the repository's
general licence label as a substitute for the per-voice card or as proof of
publicity / endorsement rights for any unidentified source speaker.

## Vietnamese: VieNeu-TTS v3 Turbo

- SDK/source: https://github.com/pnnbao97/VieNeu-TTS
- Model: https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Turbo
- Codec: https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX
- Model and bundled preset assets: Apache-2.0 according to the model card.
- The model card states that the bundled preset voices were supplied with
  appropriate speaker/rightsholder consent and that generated audio may be
  used in commercial and monetized content.
- Attribution: “Generated with VieNeu-TTS v3 Turbo by Phạm Nguyễn Ngọc Bảo,
  using its bundled preset voices and MOSS Audio Tokenizer Nano. Changes:
  new English/Vietnamese text-to-speech audio generated and loudness-
  normalized; VoiceStudio provenance watermark embedded.”

The model card currently documents 23 preset voices for SDK v3.7.1. This
build pins the SDK package version separately and stores the actual preset
list returned by that version, because the roster can change between
releases.

## VoiceStudio provenance

All generated WAVs are sent through
`backend/services/watermark.py:mark_synthetic(force=True)`, which uses
Meta AudioSeal when its runtime is available. Publication requires a
positive `detect_watermark` result identifying the VoiceStudio watermark
after the final WAV is written. The watermark is a synthetic-audio provenance
signal, not a copyright grant, licence, or proof of speaker consent.
