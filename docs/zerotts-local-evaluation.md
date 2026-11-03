# ZeroTTS local Vietnamese CPU evaluation

## Why this model is being screened

ZeroTTS is a Vietnamese-first ONNX TTS release. Its maintainers report a
202M-parameter model, a streaming path, and CPU throughput around 0.5x realtime
on their own benchmark machine. Those are maintainer-reported figures, not
VoiceStudio results. This workflow measures the actual GitHub-hosted CPU
runner before comparing it against KorvaTTS.

## Exact release and licensing snapshot

- Source: https://github.com/zeroweight-ai/ZeroTTS
- PyPI package: zerotts==0.1.5
- PyPI wheel SHA-256:
  9b4ceade901c224db33f675794c2c2f7c6d9190fd8f97b74c85efe62cef1c04b
- Model: https://huggingface.co/zeroweight-ai/ZeroTTS
- Inference: ONNX Runtime CPU, NumPy, tokenizer and codec decoder; no
  PyTorch is needed for TTS synthesis itself.
- Code and model weights: MIT as declared by the project.
- Bundled MOSS-Audio-Tokenizer-Nano ONNX decoder graphs: Apache-2.0.
- Vietnamese text normalization adapts soe-vinorm, MIT.
- The separate ZeroBench-TTS evaluation dataset is CC-BY-NC-4.0. Its license
  does not automatically apply to the model weights, but its audio must not be
  copied into VoiceStudio production assets.

The README lists training-source corpora VIVOS, viVoice, PhoAudiobook and
Emilia. The MIT declaration on the released code/weights is not a substitute
for separately reviewing training-data provenance, the underlying corpus
terms, and any speaker/source-recording permissions before commercial
redistribution or production promotion.

## Voice inventory and a hard limitation

The current weights repo bundles eight named Vietnamese voice presets. The
speaker conditioning is a small latent array. However, the current public
release does not include the reference-audio voice encoder that creates
those latents. The Python package can load a preset or a latent pack but
cannot locally create a new voice from a new WAV recording.

This benchmark therefore tests the eight shipped presets only. It does not
call the project's hosted voice-latent service, and it does not count
unconditional samples, seeds or latent arithmetic as new speaker identities.
A local encoder or contributor-recording pipeline would need to be developed
or separately licensed before claiming thousands of new identities.

## Benchmark design

- Resolve and record an immutable Hugging Face model commit.
- Verify and install the PyPI 0.1.5 wheel by its published SHA-256.
- Run ONNX Runtime CPU only, with a four-thread cap.
- Load all eight bundled presets and warm up the runtime.
- Render four Vietnamese cases per preset:
  - natural conversational Vietnamese,
  - dates, numbers and proper names as raw text,
  - the same numbers/names after normalize_vi_text,
  - Vietnamese with embedded English technical terms.
- Run a separate streaming pass for every preset; record time-to-first-audio
  as the wall time to the first decoded chunk, and total stream generation
  time.
- Record one-shot wall time, model load, warm-up, generated duration, internal
  time-to-first-frame, peak RSS during TTS, and hashes.
- Normalize all WAVs to mono 48 kHz PCM-24, embed and verify VoiceStudio
  AudioSeal provenance, and run the shared technical audio checks.
- Upload anonymous listening audio and an unfilled native-Vietnamese score
  sheet. Keep technical voice/text mapping separate from the blind samples.

## What counts as success

A successful run means the model loaded, emitted finite audio, passed the
configured signal checks, produced valid 48 kHz PCM-24 files and verified the
provenance watermark. It is not a human quality verdict.

Before promoting any voice or inference setting, native Vietnamese listeners
must assess tone accuracy, numbers, names, consonants, code-switching,
naturalness, prosody, and long-form continuity. English-only synthesis is
outside the scope of this Vietnamese-first model.

## Artifacts and workflow

The benchmark is branch-scoped to experiment/zerotts-vietnamese-cpu-benchmark.
It does not alter the production voice-library manifest, published assets or
release workflow. It does not use any hosted TTS endpoint or paid synthesis
service.


## ONNX external-data cache handling

The HF Hub cache stores snapshot files as symlinks to content-addressed blobs.
The ZeroTTS MOSS decoder graph uses ONNX external tensor data. On a Linux
runner, ONNX Runtime resolves the graph symlink to its blob directory and
rejects its sibling external-data path as escaping the allowed model folder.

The benchmark therefore downloads the exact immutable model revision and
materializes the snapshot into a temporary physical directory with symlinks
dereferenced before creating ONNX sessions. This does not modify the model or
weights; it preserves the graph and its external data files as siblings in a
normal local directory. The copy lives under /tmp, outside the uploaded
benchmark artifact, and is not added to the VoiceStudio library.

## Measured GitHub-hosted CPU baseline — 3 November 2026

The first complete VoiceStudio run is GitHub Actions run 41584156577
(artifact zerotts-vietnamese-cpu-41584156577), on Ubuntu 24.04 with
CPUExecutionProvider and a four-thread cap:

| Measurement | Result |
|---|---:|
| Model snapshot size | 999.4 MiB |
| Model load | 6.264 s |
| Runtime warm-up | 0.205 s |
| Peak RSS during TTS | 3,068.6 MiB |
| One-shot samples | 32 |
| Streaming samples | 8 |
| Total output files | 40 / 40 technically validated |
| One-shot speech | 280.64 s |
| One-shot synthesis | 527.95 s |
| Audio / compute (one-shot) | 0.532x |
| Conventional compute / audio (one-shot) | 1.881x |
| Streaming speech | 70.08 s |
| Streaming synthesis | 132.58 s |
| Audio / compute (streaming) | 0.529x |
| Mean time to first streaming chunk | 0.272 s |
| Maximum time to first streaming chunk | 0.284 s |
| AudioSeal verification | 40 / 40 passed |
| PCM validation | 40 / 40 mono, 48 kHz, PCM-24, zero clipped samples |

The ratio terminology matters: this report uses audio / compute (greater
than 1 means faster than real time). Conventional RTF is compute / audio
(lower than 1 means faster than real time). On this four-thread hosted runner,
ZeroTTS took about 1.88 seconds of compute for one second of one-shot audio.
That is slower than real time, despite the upstream README's approximately
0.5x CPU RTF result on its own eight-thread benchmark machine. The two
measurements use different hardware/thread conditions and should not be
treated as contradictory without reproducing the upstream machine.

The first decoded streaming chunk arrived in 0.272 seconds on average. This is
not the same as the maintainer's approximately 70 ms claim, and it is not
instantaneous real-time playback; it is simply the measured first-chunk
latency of this GitHub-hosted runner.

### Vietnamese text-case results

| Text case | Samples | Audio / compute | Compute / audio |
|---|---:|---:|---:|
| Natural Vietnamese | 8 | 0.545x | 1.835x |
| Raw dates, numbers and names | 8 | 0.534x | 1.872x |
| Same text after normalization | 8 | 0.531x | 1.883x |
| Vietnamese with English technical terms | 8 | 0.524x | 1.908x |

Every generated file passed signal and watermark checks, but those are not
quality metrics. The near-silence ratio averaged approximately 0.157 across
the 40 outputs (range 0.088–0.253); this may include natural inter-word pauses
and cannot be interpreted as an intelligibility score. The blind score sheet
is still empty. No ASR/WER or MOS score was computed.

### Package metadata note

PyPI distribution metadata reported zerotts==0.1.5, while the imported
module's __version__ attribute was unset (None). The benchmark records this
as unset and raises a metadata-mismatch flag. This did not stop synthesis,
but the discrepancy should be resolved upstream before pinning the package
for a production release.

### Comparison with the latest KorvaTTS CPU tests

Both models were screened on Ubuntu 24.04 GitHub-hosted CPU runners with a
four-thread cap. On the ten-preset KorvaTTS step sweep, 32 steps achieved
2.455x audio / compute with 1,451 MiB peak RSS; 8 steps achieved 7.933x.
The separate 45-sample KorvaTTS Vietnamese stress matrix achieved 8.671x,
4.920x and 2.643x at 8, 16 and 32 steps, respectively, with 1,643.9 MiB peak
RSS.

By comparison, this ZeroTTS run achieved 0.532x audio / compute and
3,068.6 MiB peak RSS. In raw CPU throughput, KorvaTTS was roughly 4.6–5.0x
faster than ZeroTTS at its 32-step baseline, while using about half the peak
memory. This is a compute comparison only: KorvaTTS's lower-step quality and
both models' perceptual quality still require blind native-Vietnamese review.

Current decision: retain ZeroTTS as a Vietnamese-specialist research
candidate, but do not select it as VoiceStudio's high-volume CPU renderer yet.
It has only eight bundled presets and lacks the published local speaker
encoder needed to create additional voice latents. It cannot satisfy the
thousands-of-identities target by itself. KorvaTTS is currently the stronger
CPU throughput candidate, pending quality and training-source rights review.