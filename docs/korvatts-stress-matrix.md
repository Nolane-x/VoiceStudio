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


## First measured stress run — 3 November 2026

GitHub Actions run 41582681593 completed successfully with 45 / 45 samples.

- Model revision: e5c8c218e93c1d8daa53bfe0e62b8fbc5a5e991d
- Model load: 0.97 seconds
- Peak RSS: 1,643.9 MiB
- Total audio: 504.23 seconds
- Total synthesis: 117.12 seconds
- Blind review sheet remains blank; no human quality grade is assigned.

| Text case | 8-step audio/compute | 16-step audio/compute | 32-step audio/compute | 8-vs-32 speed ratio |
|---|---:|---:|---:|---:|
| Natural tones | 7.618x | 4.399x | 2.395x | 3.18x |
| Dates, numbers and names | 9.367x | 5.258x | 2.795x | 3.35x |
| Vietnamese with English technical terms | 8.608x | 4.886x | 2.633x | 3.27x |

These are the observed audio-duration / synthesis-time ratios within this run.
They are useful for relative comparison, but absolute throughput can vary
between hosted runners. The consistent in-run result is that eight steps are
about 3.2–3.35x faster than 32 steps across all three test cases.

No ASR/WER, MOS or human preference result was measured. Similar waveform
RMS/peak values do not prove Vietnamese tones, names, consonants or prosody
are preserved. Keep 32 steps as the quality-oriented baseline until native
listeners complete the blind A/B review.

Artifact: run 41582681593, artifact korvatts-vietnamese-stress-41582681593.
It contains 45 anonymous WAV files and an empty human-review CSV.
