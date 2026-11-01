# Benchmarks

Measured numbers per engine and device — how long a generation actually
takes on real hardware. Every number here is produced by the in-repo
harness, on named hardware, at a named version; nothing is estimated.

## How numbers are measured

```bash
# stop the app first — a running backend holds a model and skews numbers
uv run python scripts/bench_pipeline.py            # everything
uv run python scripts/bench_pipeline.py tts        # just the TTS stage
```

`scripts/bench_pipeline.py` profiles each pipeline stage one at a time,
memory-safely: it refuses to start a stage without enough free RAM and
unloads models between stages. See [performance.md](performance.md) for
what each stage spends its time on.

The `tts` stage emits the two values this table collects:

- **RTF** (real-time factor) — seconds of compute per second of generated
  audio, printed next to each warm measurement. RTF < 1 means faster than
  real time. Use the **short line (warm)** RTF for the table.
- **Peak VRAM** — printed on CUDA only. MPS is unified memory and CPU has
  no VRAM; subprocess-isolated engines allocate outside the harness's view
  (it prints `n/a` for them). Leave the column blank in all those cases.

## Results

No verified rows yet — this table fills from maintainer runs and community
submissions.

| Engine | Device | RTF (warm) | Peak VRAM (GB) | App version | Source |
|---|---|---|---|---|---|
| _none yet — contribute yours below_ | | | | | |

Column meanings: **Engine** — the TTS engine the harness resolved (printed
at stage start). **Device** — one string naming what ran the model, e.g.
`RTX 3060 12 GB`, `Apple M2 Pro`, `Ryzen 7 5800X (CPU)`. **RTF (warm)** —
the short-line warm RTF from the harness. **Peak VRAM** — the harness's
CUDA peak, blank on MPS/CPU. **App version** — from `Settings → About`.
**Source** — a link to the PR that added the row.

## Contributing a row

1. Run the harness on an otherwise-idle machine (app stopped) and copy its
   summary table.
2. Open a PR adding one row using the column meanings above, and paste the
   raw harness output into the PR description — that PR link becomes the
   row's **Source**.
3. One row per engine+device pair; a newer app version replaces the old row.

Numbers from different machines aren't directly comparable — that's fine.
The point is honest expectations ("this engine on this class of GPU ≈ this
fast"), not a leaderboard.
# GitHub Actions TTS candidate benchmark

VoiceStudio's local application benchmark above measures engines on a user's
hardware. The separate GitHub-hosted narration service has an opt-in benchmark
for comparing the voices used by the Nolane video-production pipeline.

Run **Actions → Benchmark TTS candidates** and choose English, Vietnamese or
both. The workflow also runs for pull requests that change its benchmark,
model-pin, watermark or shared voice-builder inputs. Inference happens on
GitHub-hosted CPU runners; no local model installation, Electron build or
self-hosted GPU is required.

The artifact `tts-candidate-benchmark-<run_id>` contains:

- `blind-listening-review.zip` — a **shareable blind-review package** with
  neutral `sample-001.wav` filenames, reference scripts, browser gallery
  and blank score sheet. It contains no engine/voice mapping, ASR output or
  objective benchmark metrics.
- `index.html` and `blind-samples/*.wav` — the same blind gallery and
  neutral-name audio inside the full artifact.
- `human-review.csv` — ratings keyed by neutral `blind_sample_id`.
- `benchmark.json` — the separate analyst mapping from blind sample IDs to
  model/voice, with revisions, checksums, audio measurements, ASR diagnostics,
  rights notices and per-sample failures.
- `tts-candidate-benchmark.zip` — the full deterministic analyst bundle.

Share only `blind-listening-review.zip` with listeners. After collecting
scores, join `blind_sample_id` to the separate `benchmark.json` to reveal
which engine produced each voice. Do not share the full analyst bundle before
the blind review is complete.


The current comparison includes Piper LibriTTS High (English baseline),
VieNeu-TTS v3 Turbo (English/Vietnamese), Kokoro-82M (English), and
Supertonic 3 (English/Vietnamese comparison candidate). Each engine uses
matched text scenarios and a warm-up call before inference timing.

Metrics have limits: RTFx is generated audio duration divided by synthesis
wall time; English token error is a whitespace-token WER; Vietnamese token
error counts whitespace-delimited syllables, not lexical words; CER is
character error rate. These measures do not establish naturalness, emotion,
speaker similarity or editorial suitability. Listen to each complete sample
and score naturalness, pronunciation, prosody and emotion before selecting
a production narrator.

Supertonic 3 remains comparison-only. Its OpenRAIL-M model terms require
separate review; this benchmark does not grant commercial-use clearance.
Piper's source evidence also does not establish blanket commercial or
publicity rights. VieNeu and Kokoro retain their own upstream rights and
attribution notices in the result manifest.


## First verified GitHub Actions voice-service baseline

The first full matched-sample run completed successfully:

- Workflow run: [#6](https://github.com/Nolane-x/VoiceStudio/actions/runs/41285695971)
- Benchmark source commit: `9c43ebba543bbb9e4b63092e6f1ffb491038fba4`
- Built: 2026-11-01 07:47 UTC
- Runner: GitHub-hosted Ubuntu 24.04 CPU
- Samples: **24/24 rendered**, 0 candidate/sample failures.
- Output: all WAVs are mono 48 kHz PCM-24; all SHA-256 values match the manifest; all 24 saved samples passed VoiceStudio watermark detection; all 24 ASR runs completed.
- ASR: faster-whisper small, CPU int8.
- Artifact SHA-256: `b776e66460b7f1bd3f62517f0236eaa3571adaf3f7d17290f753161f5eafd6aa`.

| Engine | Language | Samples | Mean RTFx | Mean CER | Mean token error |
|---|---:|---:|---:|---:|---:|
| Supertonic 3 | English | 4 | 5.031 | 2.47% | 4.84% WER |
| Supertonic 3 | Vietnamese | 4 | 5.362 | 21.35% | 25.83% syllable error |
| VieNeu v3 Turbo | English | 4 | 1.301 | 6.21% | 10.74% WER |
| VieNeu v3 Turbo | Vietnamese | 4 | 1.327 | 6.02% | 12.18% syllable error |
| Kokoro-82M | English | 4 | 2.979 | 2.62% | 4.84% WER |
| Piper LibriTTS High | English | 4 | 4.165 | 3.10% | 5.73% WER |

RTFx is audio duration divided by warmed TTS synthesis time; higher means faster than real time. It excludes ASR, watermarking and mastering. Vietnamese token error counts whitespace-delimited syllables, not lexical words. These numbers are diagnostics from two short prompts per voice, not a controlled MOS study, and should not be used as an automatic quality leaderboard.

**Current engineering decision:** retain VieNeu as the Vietnamese production default. Its mean ASR diagnostics were better than the Supertonic aggregate in this small sample; Supertonic F3 was much closer than M1, but the engine remains comparison-only because its OpenRAIL-M terms need separate review. For English, Kokoro and Supertonic showed similar ASR diagnostics, with Supertonic faster on this CPU runner; retain Kokoro as the existing production candidate until a blind human listening review is complete. Piper remains a baseline with restricted/uncleared rights evidence.

The separate blind-review ZIP contains only anonymized samples,
reference text, a rating form and neutral sample IDs; it has no model mapping,
ASR transcript or objective score. The full analyst artifact retains the
mapping in `benchmark.json`. After listening, export scores and join
`blind_sample_id` to that manifest. **No engine has been promoted or replaced
by this run.**
