# KorvaTTS Vietnamese text-case stress matrix

## Goal

Expand the single-passage inference-step comparison into a small Vietnamese
stress set to avoid selecting a faster step count from only one easy sentence.

## Matrix

- Five bundled KorvaTTS voice styles
- Three text cases: natural tones, numbers/dates/proper names, and Vietnamese
  with embedded English technical terms
- 8, 16 and 32 flow-matching steps
- 45 total WAV samples
- Same deterministic seed per voice/text case across the three step counts
- ONNX Runtime CPU, VoiceStudio FFmpeg normalization, AudioSeal verification,
  waveform validation and SHA-256

## Evaluation boundaries

This test measures throughput and technical signal integrity. It does not
automatically grade Vietnamese tone accuracy, name pronunciation, code-switch
quality, naturalness or prosody. Human native-Vietnamese listening is required
before any speed setting is promoted.

The stress matrix uses five of the ten available preset styles; it introduces
no new contributor voices or speaker identities. Data/source-voice rights
remain separate promotion gates.

The branch-scoped workflow is experimental and does not alter the production
voice-library manifest or release output.
