# Voice library expansion strategy

## Target

Build a catalog of thousands of distinct, usable voice identities for Vietnamese and English creators. Keep identity, language variant, model capability, and voice-design prompt as separate concepts.

The current source-derived inventory estimate is approximately:
- 904 English Piper LibriTTS speaker IDs (rights evidence remains restricted per voice; not blanket commercial clearance).
- 4 curated Kokoro English presets (Apache-2.0 model and packaged voice assets).
- About 23 VieNeu preset identities. The same identities can generate Vietnamese and bilingual English variants.

This is approximately 931 distinct source identities and 954 language variants. These are inventory estimates, not a claim that a full catalogue release has been built or that every candidate is commercially cleared.

## New 2,000-profile expansion pool
Each profile is assigned one of 16 creator-facing archetypes: cinematic documentary narrator, warm history storyteller, friendly educator, expert explainer, immersive audiobook performer, reflective storyteller, conversational podcast host, curious interviewer, short-form creator hook, energetic social-video narrator, professional presenter, premium brand storyteller, credible news anchor, journalistic explainer, calm wellness guide, or mindful reflection narrator. These are generic role directions, never descriptions of named creators or identifiable voices.


The deterministic catalog generator creates 1,000 Vietnamese and 1,000 English voice-design blueprints. These are not WAVs, saved provider voices, or verified speaker identities. They are original, non-impersonating descriptions with accent/locale, timbre, pitch, pace, delivery, use-case and a deterministic seed.

The no-cost GitHub Actions catalog workflow builds these blueprints without model downloads, API keys, or paid generation. A separate manual workflow can create up to 8 provider design requests per run (each can return up to 3 previews) using the ElevenLabs Voice Design API. It is disabled unless confirm_paid_api_usage=true and ELEVENLABS_API_KEY is configured. It does not save persistent account voices or change a production model.

**Voice Design previews are account-scoped and cannot be shared in the ElevenLabs public Voice Library.** The public marketplace track must instead use Professional Voice Clones from voice actors who have explicitly consented to sharing and accepted the provider's terms, or use a provider that grants the necessary redistribution rights. Never clone or imitate a celebrity, public figure, or identifiable creator.

## External sources and eligibility

| Source | Coverage and scale | Current decision |
|---|---|---|
| Google Cloud Chirp 3: HD | 29 named voice styles; supports vi-VN and English locales en-US, en-GB, en-AU, en-IN. | Strong paid cloud candidate; billing required; validate exact locale/voice pairs. |
| ElevenLabs Voice Design | Original synthetic identity design; multiple previews per request. | Private-account previews only; paid requests require explicit manual dispatch and API key. |
| VieNeu-TTS v3 Turbo | About 23 dynamic preset identities with Vietnamese and bilingual English output. | Current Vietnamese production candidate; read the live preset roster from the pinned SDK. |
| Kokoro-82M | Curated English voices and very high Hub usage. | Retain as English candidate; measure listener preference, not just downloads. |
| OmniVoice Vietnamese fine-tunes | Published 1,000-hour, 152-speaker Vietnamese corpus. | Research-only: dataset CC-BY-NC-SA-4.0; do not use in monetized production. |
| G-OmniVoice | Vietnamese-specific voice design/cloning; gated access. | Quarantine until tokenizer, dataset and downstream rights are reviewed. |
| Fish Audio S2 Pro | Multilingual incl. Vietnamese; strong benchmark visibility. | Licensed-provider candidate only; separate commercial license required. |
| Fun-CosyVoice3 | Apache-2.0, 9 languages incl. English; no Vietnamese in published list. | English comparison candidate only. |
| Pocket TTS | CPU-friendly streaming; English and several European languages, not Vietnamese. | English streaming candidate; review access terms. |
| FPT AI / Viettel AI / Vbee | Vietnamese cloud voices and regional variants. | Integration candidates; provider agreement and per-voice terms required. |

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
