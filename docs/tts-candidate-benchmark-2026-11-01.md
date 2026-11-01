# VoiceStudio TTS candidate benchmark — 2026-11-01

**Workflow run:** [Benchmark TTS candidates, run 41321565278](https://github.com/Nolane-x/VoiceStudio/actions/runs/41321565278)  
**Source commit:** `fe9d31c54096e41db3fe0c8cbc5a15f2feb35ef0`  
**Runner:** GitHub-hosted `ubuntu-24.04`, CPU inference, pinned dependencies and model revisions  
**Result:** 48/48 matched samples rendered; 0 failures.

## Scope

The benchmark rendered four matched scenario types (story, numbers, conversation and long-form narration) in English and Vietnamese where each candidate supports the language. Two voice identities per engine/language were used. Every retained file was normalized to mono 48 kHz PCM-24, VoiceStudio-watermarked and checked after saving. SHA-256 hashes and pinned source revisions are recorded in the analyst artifact.

| Engine | Language | Voice identities | Samples | Mean RTFx | Mean ASR token error | Mean CER | Rights interpretation |
|---|---:|---:|---:|---:|---:|---:|---|
| VieNeu v3 Turbo | Vietnamese | 2 | 8 | 1.720 | 7.76% | 3.45% | Upstream model card states consent for bundled presets and permits commercial use of generated audio; retain attribution |
| Supertonic 3 | Vietnamese | 2 | 8 | 2.029 | 17.88% | 14.17% | OpenRAIL-M weights; manual licence review required before production |
| VieNeu v3 Turbo | English | 2 | 8 | 1.704 | 8.02% | 4.42% | Bilingual output, not a claim of native-English speaker identity |
| Kokoro-82M | English | 2 | 8 | 2.402 | 2.76% | 1.29% | Apache-2.0 model and bundled voice assets; no real-person endorsement rights |
| Piper LibriTTS High | English | 2 | 8 | 3.645 | 4.77% | 2.05% | Not cleared for commercial use by this build; excluded from commercial recommendations |

RTFx is generated-audio duration divided by warm synthesis wall time; greater than 1 means faster than real time. The benchmark times synthesis after a warm-up, not model download, installation, mastering, watermarking or ASR. These numbers describe this GitHub-hosted runner and must not be compared directly with another machine or run.

**ASR token error is a diagnostic, not a MOS score.** English token error uses whitespace-delimited words. Vietnamese token error uses whitespace-delimited syllables, not lexical words. CER is character error rate from Faster-Whisper small on CPU. These metrics can expose pronunciation/intelligibility issues but cannot judge naturalness, tone quality, emotional fit, prosody, speaker preference or long-form continuity.

## What this run suggests — and what it does not

- VieNeu is the stronger Vietnamese candidate in this first objective screen: lower mean token error and CER than Supertonic on the matched passages. This does not prove it is preferred by native listeners.
- Kokoro has the lowest English ASR error among the tested English candidates. Its upstream A/A- quality grades are source-author estimates, not independently measured MOS.
- Piper is fast on this runner, but its rights evidence is not sufficient for blanket commercial promotion.
- Supertonic is a useful CPU comparison candidate, but its Vietnamese ASR error is materially higher in this small sample and OpenRAIL-M use restrictions remain separate from technical quality.
- VieNeu's English bilingual mode is useful for coverage, but its ASR diagnostic is weaker than Kokoro in this run; compare it with a native-English voice before choosing it for an English-first production.

## Blind listening review

The workflow uploaded a separate anonymous review package: [blind-listening-review-41321565278](https://github.com/Nolane-x/VoiceStudio/actions/runs/41321565278/artifacts/13090236199). Independent integrity checks found:

- 48 neutral-name WAV files, each mono 48 kHz PCM-24.
- The 48 IDs match exactly across the WAV set, HTML gallery and CSV score sheet.
- The gallery contains no engine names, voice IDs, model revisions, ASR transcripts or objective metrics.
- The analyst mapping and ASR results are in the separate [analysis artifact](https://github.com/Nolane-x/VoiceStudio/actions/runs/41321565278/artifacts/13090246225).

Human ratings have **not** been completed by this automated run. A reviewer must score naturalness, pronunciation, prosody and emotional fit while listening blind, then join the score CSV to the analyst manifest only after submitting ratings. No production voice is promoted by RTFx, ASR or benchmark completion.

## Next evaluation gate

1. Complete native-speaker blind listening for both Vietnamese and English. Add explicit Vietnamese tone, proper-name, number-reading and regional-accent notes.
2. Repeat with more speakers and a wider script set before claiming stable rankings.
3. Run separate premium-provider comparisons only with explicit paid-use confirmation and authorized API keys; compare Eleven v4, Gemini 3.8 and Grok as provider-managed candidates, not redistributable voice assets.
4. Keep popularity (provider usage/trending/cloning signals), human preference, ASR intelligibility, speed and rights clearance as separate evidence dimensions.

The result is a reproducible screening baseline, not proof of the best voice or a market-wide popularity ranking.
