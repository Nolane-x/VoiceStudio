# Voice library expansion strategy

## Target

Build a catalog of thousands of distinct, usable voice identities for Vietnamese and English creators. Keep identity, language variant, model capability, and voice-design prompt as separate concepts.

The current source-derived inventory estimate is approximately:
- 904 English Piper LibriTTS speaker IDs (rights evidence remains restricted per voice; not blanket commercial clearance).
- 4 curated Kokoro English presets (Apache-2.0 model and packaged voice assets).
- 25 VieNeu preset identities, from the pinned SDK metadata in GitHub Actions smoke run #55. The same identities can generate Vietnamese and bilingual English variants.

This is approximately 933 distinct source identities and 958 language variants. These are inventory estimates, not a claim that a full catalogue release has been built or that every candidate is commercially cleared.

## New 2,000-profile expansion pool
Each profile is assigned one of 16 creator-facing archetypes: cinematic documentary narrator, warm history storyteller, friendly educator, expert explainer, immersive audiobook performer, reflective storyteller, conversational podcast host, curious interviewer, short-form creator hook, energetic social-video narrator, professional presenter, premium brand storyteller, credible news anchor, journalistic explainer, calm wellness guide, or mindful reflection narrator. These are generic role directions, never descriptions of named creators or identifiable voices.


The deterministic catalog generator creates 1,000 Vietnamese and 1,000 English voice-design blueprints. Vietnamese profiles default to ElevenLabs Text-to-Voice v3 (`eleven_ttv_v3`), which supports Vietnamese; English profiles default to `eleven_multilingual_ttv_v2`. The preview runner validates explicit overrides and uses language-safe automatic routing for older profile artifacts. These are not WAVs, saved provider voices, or verified speaker identities. They are original, non-impersonating descriptions with accent/locale, timbre, pitch, pace, delivery, use-case and a deterministic seed.

The no-cost GitHub Actions catalog workflow builds these blueprints without model downloads, API keys, or paid generation. A separate manual workflow can create up to 8 provider design requests per run (each can return up to 3 previews) using the ElevenLabs Voice Design API. It is disabled unless confirm_paid_api_usage=true and ELEVENLABS_API_KEY is configured. It does not save persistent account voices or change a production model.

**Voice Design previews are account-scoped and cannot be shared in the ElevenLabs public Voice Library. A selected preview can be saved to the account through `POST /v1/text-to-voice`, but it remains workspace-only; only Professional Voice Clones can be published to the public Voice Library.** The public marketplace track must instead use Professional Voice Clones from voice actors who have explicitly consented to sharing and accepted the provider's terms, or use a provider that grants the necessary redistribution rights. Never clone or imitate a celebrity, public figure, or identifiable creator.

## External sources and eligibility

| Source | Coverage and scale | Current decision |
|---|---|---|
| Google Gemini 3.8 Flash TTS / Flash-Lite | 130 / 101 languages; Vietnamese and English; 30 prebuilt voices and a separate 2,000+ Extended Voice Library in Gemini Enterprise. | High-priority paid provider benchmark; managed voices are not redistributable library files. |
| Mistral Voxtral TTS 3 | 35 languages / 50+ dialects; one Vietnamese preset and multiple UK/US English presets. | High-priority paid provider benchmark; voice cloning only from explicitly authorized recordings. |
| Google Cloud Chirp 3: HD | 29 named voice styles; supports vi-VN and English locales en-US, en-GB, en-AU, en-IN. | Strong paid cloud candidate; billing required; validate exact locale/voice pairs. |
| ElevenLabs Voice Design | Original synthetic identity design; up to three previews per request. Text-to-Voice v3 supports Vietnamese; Multilingual v2 does not list Vietnamese. | Private-account previews only; route VI to `eleven_ttv_v3`, EN to `eleven_multilingual_ttv_v2`; paid requests require explicit manual dispatch and API key. |
| VieNeu-TTS v3 Turbo | 25 preset identities listed by the pinned VieNeu SDK metadata; smoke run #55 exercised two presets across Vietnamese and bilingual English output. | Current Vietnamese production candidate; read the live preset roster from the pinned SDK. |
| Kokoro-82M | Curated English voices and very high Hub usage. | Retain as English candidate; measure listener preference, not just downloads. |
| OmniVoice Vietnamese fine-tunes | Published 1,000-hour, 152-speaker Vietnamese corpus. | Research-only: dataset CC-BY-NC-SA-4.0; do not use in monetized production. |
| G-OmniVoice | Vietnamese-specific voice design/cloning; gated access. | Quarantine until tokenizer, dataset and downstream rights are reviewed. |
| Fish Audio S2 Pro | Multilingual incl. Vietnamese; strong benchmark visibility. | Licensed-provider candidate only; separate commercial license required. |
| Fun-CosyVoice3 | Apache-2.0, 9 languages incl. English; no Vietnamese in published list. | English comparison candidate only. |
| Pocket TTS | CPU-friendly streaming; English and several European languages, not Vietnamese. | English streaming candidate; review access terms. |
| FPT AI / Viettel AI / Vbee | Vietnamese cloud voices and regional variants. | Integration candidates; provider agreement and per-voice terms required. |

## Market-demand discovery

VoiceStudio tracks different evidence families independently:

- Hugging Face TTS trending position, downloads, likes, language tags and model recency indicate open-model discovery/adoption. A weekly Actions workflow snapshots the public Hub API; each row remains discovery-only until its model card, weights, runtime and rights are checked.
- The Open TTS Leaderboard provides WER/CER, speaker-similarity and speed/streaming diagnostics. These metrics are useful for screening but do not replace blind human preference.
- Artificial Analysis Speech Arena uses blind pairwise listener comparisons and Elo-style scores for managed provider models/native voices. This is closer to listener preference than download counts, but it is not proof of adoption by YouTube channels or of per-voice rights.
- Creator/platform usage is recorded only when a provider or developer publishes auditable usage evidence. Do not infer "used by thousands of channels" from model downloads, likes, provider pricing, or leaderboard placement.

The discovery report never adds a model to the production voice library automatically. It records source snapshots and metadata; rights review, native-language smoke tests and blind listening remain separate promotion gates.

## Popularity and quality policy

- Downloads, likes, repo stars, trending filters and leaderboard standings are discovery signals, not proof of quality or rights.
- Open TTS leaderboard metrics are useful for intelligibility, speed and similarity, but the leaderboard states that objective metrics do not replace human preference.
- Use popular commercial voices only as broad market archetypes; never copy a named celebrity, creator, or identifiable voice.
- Every candidate requires blind listening in its target language/accent, signal checks, ASR diagnostics, license review and stable source/model revision before promotion.
- Count voice_identity_id separately from language_variant_id, provider_voice_id and voice_design_profile_id. A design profile or bilingual variant is not a new verified voice identity.

## Release gates

1. Discovery catalog: source/evidence recorded; no audio assets.
2. Preview candidate: provider output exists; no production use; blind evaluation.
3. Approved synthetic identity: human ratings and rights review complete; source/model revision/provider terms/hashes recorded.
4. Production voice: passes pronunciation, long-form continuity, loudness, watermark, caption alignment, stability and commercial-use checks.
5. Public distribution: only if the voice owner and provider contract explicitly permit sharing/redistribution.

## Cost and access controls

- The profile catalog workflow is free and does not synthesize audio.
- The ElevenLabs preview workflow is manual-only, requires an API secret and explicit confirm_paid_api_usage=true, and is capped at 8 design requests per run. It does not create saved voices.
- Google Cloud Chirp 3: HD requires billing. Published pricing lists 1 million characters free/month, then US$0.00003 per character. No Google Cloud calls are made by current workflows.

## Reproducibility

Profile IDs and seeds are deterministic. Full prompt-to-preview mapping is in a separate analysis artifact; blind reviewers receive only audio and neutral IDs. Production promotion is manual and never triggered by profile count alone.


### Human-approved account voice creation

The blind review CSV includes an `approve` field. After a human listener has approved a preview and entered the required scores, the separate `Promote human-reviewed Voice Design candidates` workflow can create up to eight persistent workspace voices from their existing `generated_voice_id` values. This calls the provider's create-from-preview endpoint, not a new preview-generation endpoint. The workflow requires a private repository, `ELEVENLABS_API_KEY`, and a separate `confirm_voice_creation=true` input. Candidates must pass naturalness, pronunciation, accent-fit, prosody, distinctiveness and overall score thresholds. The returned IDs are workspace-only; Voice Design voices cannot be published to the public ElevenLabs Voice Library. No preview is generated and no public distribution is attempted by the promotion step.


### Official provider documentation

- [ElevenLabs Voice Design API](https://elevenlabs.io/docs/api-reference/text-to-voice/design): previews return a `generated_voice_id` and base64 audio.
- [ElevenLabs Create a voice](https://elevenlabs.io/docs/api-reference/text-to-voice/create): saves an existing `generated_voice_id` as an account voice.
- [ElevenLabs List voices](https://elevenlabs.io/docs/api-reference/voices/search): supports account search by name, description and labels, used to reconcile interrupted promotion requests.
- [ElevenLabs Voice Library sharing rules](https://elevenlabs.io/docs/help-center/product/voices/voice-library/what-is-the-voice-library): only Professional Voice Clones can be publicly shared; Voice Design voices are not shareable.
- [Google Cloud Chirp 3 HD voice IDs](https://docs.cloud.google.com/text-to-speech/docs/list-voices-and-types): lists Chirp 3 styles and supported Vietnamese/English locale voices.


### Duplicate-safe voice promotion

The create-from-preview endpoint does not document an idempotency-key header. VoiceStudio therefore tags each created account voice with the original `generated_voice_id` and searches the account through the List Voices API before every create request. If a POST times out or returns an ambiguous server error, the script searches again and records an `unknown` outcome unless it can find the matching voice. A later run can reconcile that ID through the same label. If the voice is still not visible, another POST is blocked unless an operator explicitly sets `confirm_retry_unknown=true` after checking My Voices. The optional `previous_ledger_run_id` also preserves completed IDs and retries only failed/unprocessed entries. This is deliberately fail-closed to avoid creating duplicate account voices.
