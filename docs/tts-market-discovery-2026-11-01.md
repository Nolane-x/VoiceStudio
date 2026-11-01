# TTS market and developer-adoption snapshot — 2026-11-01

This report separates what developers download, what providers expose as voice catalogs, and what listeners prefer. These measurements are not interchangeable.

## Open-model discovery

VoiceStudio's public Hugging Face Hub discovery workflow found 176 TTS model records with zero query errors on 2026-11-01.

- Run: [Discover trending TTS models](https://github.com/Nolane-x/VoiceStudio/actions/runs/41318740964)
- Artifact: [dated discovery snapshot](https://github.com/Nolane-x/VoiceStudio/actions/runs/41318740964/artifacts/13088272862)
- Snapshot time: 2026-11-01T14:57:42Z

Selected results from that snapshot:

| Model | Downloads | Likes | Trending score | Hub language tags | License tag | Interpretation |
|---|---:|---:|---:|---|---|---|
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) | 11,247,512 | 7,320 | 38 | EN | Apache-2.0 | Strong English developer adoption signal |
| [OmniVoice](https://huggingface.co/k2-fsa/OmniVoice) | 2,857,996 | 1,636 | 37 | EN, VI | Not declared | High developer discovery; full weights/data rights need review |
| [VieNeu-TTS v3 Turbo](https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Turbo) | 1,850,767 | 94 | 4 | EN, VI | Apache-2.0 | Strong Vietnamese-capable candidate; keep attribution and preset consent terms |
| [VoxCPM2](https://huggingface.co/openbmb/VoxCPM2) | 989,625 | 1,746 | 20 | EN, VI | Apache-2.0 | Strong model discovery; review all assets and data provenance |
| [Supertonic-3](https://huggingface.co/Supertone/supertonic-3) | 83,227 | 1,031 | 13 | EN, VI | OpenRAIL | Useful technical candidate, but review restrictions before commercial use |
| [Fish Audio S2 Pro](https://huggingface.co/fishaudio/s2-pro) | 47,524 | 1,487 | 15 | EN, VI | Other | License review required |
| [Fish Audio Drama-3](https://huggingface.co/fishaudio/drama-3) | 33,436 | 1,130 | 98 | EN, VI | Other | High trending signal; rights review required |
| [Kokoro Vietnamese](https://huggingface.co/contextboxai/Kokoro-Vietnamese) | 28,611 | 33 | 0 | VI | Apache-2.0 | Repository tag does not prove consent/data rights for each speaker |
| [ViVoice / F5-TTS Vietnamese](https://huggingface.co/hynt/F5-TTS-Vietnamese-ViVoice) | 6,623 | 60 | 1 | VI | CC-BY-NC-SA-4.0 | Non-commercial research only under declared license |
| [Audio8-TTS-Realistic-0.6b](https://huggingface.co/Edge0/Audio8-TTS-Realistic-0.6b) | 4,613 | 187 | 180 | EN, VI | Apache-2.0 | Trending discovery signal; needs native-language and rights review |

These counts are model-repository downloads, not synthesized voices, listeners, deployed channels or proof of production quality. A model can generate multiple voice styles; a model license does not automatically clear every speaker recording, voice embedding or training dataset.

## Provider catalogs are not redistributable audio libraries

| Provider | Discovery surface | Available evidence | Important limit |
|---|---|---|---|
| ElevenLabs | Public Shared Voice Library; provider documents 10,000+ shared voices | Sort by trending, 1-year usage-character count and cloned-by count; filter Vietnamese/English and high-quality/professional categories | Provider-hosted IDs and previews; use through authorized account/plan. No blanket right to rehost audio or redistribute voice assets |
| Google Gemini | 30 prebuilt studio voices plus a separate Extended Voice Library exceeding 2,000 in Gemini Enterprise | Language, region and persona metadata via ListVoices; TTS must be benchmarked separately | Provider-managed voices; metadata is not a license to export or redistribute assets |
| xAI / Grok | 26 documented built-in menu options in the static snapshot | Vietnamese/English included in the supported language scope; current API can refresh the list | Not 26 independent downloadable speaker recordings, and no popularity counters are exposed |
| Google Cloud Chirp 3 HD | Named voice styles across Vietnamese and English locales | Enumerate exact locale/voice pairs through the provider API | Billing and provider terms; not public redistribution by default |
| Mistral Voxtral TTS | Vietnamese preset and UK/US English options | Authorized API samples and blind preference | Managed paid API; cloning only from explicitly authorized recordings |

Dynamic snapshots on 2026-11-01 were constrained by missing repository Actions secrets:
- xAI discovery fell back to a static 26-option documentation snapshot because `XAI_API_KEY` was not configured.
- Gemini discovery uploaded a setup report only because `GEMINI_API_KEY` was not configured.
- ElevenLabs filtered marketplace discovery requires `ELEVENLABS_API_KEY`; the workflow deliberately makes no API calls without it.

Those are configuration blockers, not evidence that provider catalogs are empty. Add keys as GitHub Actions secrets (never commit or paste them into source) to enable metadata refresh. Paid synthesis remains separately gated.

## Popularity, quality and rights are separate dimensions

VoiceStudio must retain independent evidence:

1. **Developer adoption:** model downloads, likes, stars and public integrations.
2. **Marketplace adoption:** provider usage characters, trending rank and cloned-by counts where available.
3. **Human preference:** blind pairwise Elo or MOS-like ratings, split by language, accent and use case.
4. **Intelligibility:** ASR token error and CER, which are diagnostics, not MOS.
5. **Production behavior:** number/name pronunciation, Vietnamese tones, long-form consistency, chunk seams, latency and audio signal integrity.
6. **Rights:** model, data, speaker consent, output-use and redistribution terms.

A popular model can be less preferred by native listeners; a high-ranking marketplace voice may not be redistributable; and an Apache model tag does not prove the underlying speaker recordings were consented for every downstream use. No single “trending” score can promote a production voice.

Useful human-preference source: [Artificial Analysis Text-to-Speech Arena](https://artificialanalysis.ai/text-to-speech/arena). Pairwise preference and sample counts are more relevant to listener preference than raw downloads, but they do not prove creator/channel adoption or grant redistribution rights.

## Counting contract for a catalogue of thousands

- `rendered_voice_identity`: distinct voice identity with an actual saved audio sample and canonical source/voice ID. Rendering alone does not equal production approval.
- `language_variant`: language/accent rendering of an existing identity; do not count it again as a new identity.
- `provider_managed_voice`: provider-hosted voice ID; use under provider terms unless export/redistribution is explicitly granted.
- `voice_design_blueprint`: prompt, traits and deterministic seed only; no WAV and no rendered voice identity.
- `blind_reviewed_candidate`: rendered audio reviewed without model/identity labels.
- `production_approved_voice`: rights cleared and native-language blind listening, pronunciation, long-form stability and technical gates passed.

The 2,000 VoiceStudio profiles are a blueprint pool (1,000 VI and 1,000 EN), not 2,000 completed voices. The 48-sample CPU benchmark is an engine screening experiment, not 48 approved voices.

## Execution plan

1. Use ElevenLabs shared-marketplace metadata to find provider voices already showing adoption, ranking Vietnamese and English separately. Keep IDs and previews provider-hosted.
2. Use Google and xAI catalog metadata to widen the candidate pool, without counting provider menu entries as licensed speaker identities.
3. For VoiceStudio-owned redistributable assets, prioritize consented contributor recordings, licensed voice actors and model presets with explicit data and output rights.
4. Generate real previews in bounded batches. Blind-review Vietnamese tones, names, numbers, regional accent fit, long-form reading and emotional range.
5. Promote only reviewed candidates; store provenance, model revision, output hash, rights record and test evidence with each voice.
6. Reuse the existing VoiceStudio Actions workflow from `Nolane-x/video` for downstream narration.

## Sources and exact workflow snapshots

- [Hugging Face discovery run 41318740964](https://github.com/Nolane-x/VoiceStudio/actions/runs/41318740964)
- [xAI built-in menu snapshot run 41318889030](https://github.com/Nolane-x/VoiceStudio/actions/runs/41318889030)
- [Gemini ListVoices setup run 41323404564](https://github.com/Nolane-x/VoiceStudio/actions/runs/41323404564)
- [Hugging Face Open TTS Leaderboard](https://huggingface.co/blog/open-tts-leaderboard)
- [ElevenLabs shared voices API](https://elevenlabs.io/docs/api-reference/voices/voice-library/get-shared)
- [Google Gemini TTS announcement](https://deepmind.google/blog/say-hello-to-gemini-38-text-to-speech/)
- [xAI built-in voice overview](https://docs.x.ai/developers/model-capabilities/audio/voice)
- [Artificial Analysis TTS Arena](https://artificialanalysis.ai/text-to-speech/arena)
