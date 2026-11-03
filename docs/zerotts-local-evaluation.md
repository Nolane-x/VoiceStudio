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
