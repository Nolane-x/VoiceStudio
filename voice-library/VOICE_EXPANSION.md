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
| Kokoro Vietnamese community fine-tune | 14 named Vietnamese voicepacks; public model repository is tagged Apache-2.0. | Research-only: reviewed README does not establish speaker consent or dataset rights for each voice identity; do not bundle into the public library until separately verified. |
| OmniVoice Vietnamese fine-tunes | Published 1,000-hour, 152-speaker Vietnamese corpus. | Research-only: dataset CC-BY-NC-SA-4.0; do not use in monetized production. |
| G-OmniVoice | Vietnamese-specific voice design/cloning; gated access. | Quarantine until tokenizer, dataset and downstream rights are reviewed. |
| Fish Audio S2 Pro | Multilingual incl. Vietnamese; strong benchmark visibility. | Licensed-provider candidate only; separate commercial license required. |
| Fun-CosyVoice3 | Apache-2.0, 9 languages incl. English; no Vietnamese in published list. | English comparison candidate only. |
| Pocket TTS | CPU-friendly streaming; English and several European languages, not Vietnamese. | English streaming candidate; review access terms. |
| FPT AI / Viettel AI / Vbee | Vietnamese cloud voices and regional variants. | Integration candidates; provider agreement and per-voice terms required. |

A promising Vietnamese community candidate, [contextboxai/Kokoro-Vietnamese](https://huggingface.co/contextboxai/Kokoro-Vietnamese), exposes 14 named voicepacks through the [iamdinhthuan/Kokoro-Vietnamese](https://github.com/iamdinhthuan/Kokoro-Vietnamese) runtime. The code/model repository is marked Apache-2.0, but the reviewed public README and training guide do not document per-speaker consent or complete training-data rights. VoiceStudio therefore records it as research-only and blocks public audio/catalogue publication until that separate evidence is supplied. The same distinction applies to noncommercial F5/ViVoice models: a popular or downloadable checkpoint is not a commercial voice asset.

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


## Current flagship quality target: Eleven v4

The current premium parity target is ElevenLabs Eleven v4, not the older Voice Design model ID. Provider documentation lists Eleven v4 as the flagship expressive synthesis model for more than 90 languages, including Vietnamese and English, and routes it through the Text-to-Dialogue API. The model ID is eleven_v4; it is separate from eleven_ttv_v3, which is a voice-design model used to create prompt-based previews. Do not route normal synthesis jobs to a voice-design model.

- Use Eleven v4 as the premium quality reference for creator narration, audiobooks, dialogue and emotionally directed reads.
- Use a stable, authorized provider voice ID. Never assume a Voice Design profile ID, generated_voice_id, voice-library preview ID and a persistent account voice ID are interchangeable.
- The Text-to-Dialogue endpoint recommends keeping combined input text at or below 2,000 characters per request for reliable generation. Chunk longer scripts at sentence boundaries, keep the same voice ID and language code, then run continuity/listening checks across chunk seams.
- The provider states that v4 supports Vietnamese (vi) and English (en). Still score those languages separately: a multilingual flag does not guarantee native-level pronunciation or preferred delivery for every voice.
- V4 generation is a paid-provider path. VoiceStudio never makes paid requests from CI automatically; a manual workflow requires an explicit confirmation input and a secret. Marketplace voice IDs and generated audio remain subject to provider plan, owner, commercial-use and sharing terms.

### Public shared-voice marketplace discovery

The provider exposes GET /v1/shared-voices with language, accent, locale, quality category and use-case filters. It can sort by trending, usage_character_count_1y and cloned_by_count. VoiceStudio now has a metadata-only discovery script and a weekly/manual Actions workflow that:

- Searches Vietnamese and English separately.
- Includes high_quality and professional categories; deliberately excludes famous.
- Collects trending, 1-year usage and clone-count rankings with bounded pagination.
- Creates a searchable HTML audition gallery with provider-supplied preview URLs and a JSON metadata snapshot.
- Does not synthesize audio, clone anyone, copy or rehost preview audio, or grant rights to redistribute marketplace voices.

The provider's usage counters indicate activity in that marketplace. They are not proof that a voice is loved by listeners, used by YouTube channels, or suitable for the user's particular narration. High usage only prioritizes which voices should receive blind native-language auditions.

### Vietnamese listener-preference snapshot (1 November 2026)

The current [Vietnamese Voice Arena snapshot](https://voicearena.com/tts-leaderboard/vietnamese) places Gemini 3.8 Flash-Lite, Gemini 3.8 Flash and Gemini 3.1 Flash at ranks 1–3 overall, followed by Eleven v4 at rank 4. In [media/entertainment](https://voicearena.com/tts-leaderboard/vietnamese/media-and-entertainment), Eleven v4 is rank 4; in [creator/education](https://voicearena.com/tts-leaderboard/vietnamese/content-creation-and-edu), it is rank 3. These rankings are based on blind pairwise listener votes and should be read together with their reported sample counts and uncertainty ranges. They are a market screening signal, not a promise of equal results across all accents, use cases or voice IDs.

This is why the production strategy is now multi-engine: test Eleven v4 as the paid premium reference, Gemini 3.8 Flash as the high-fidelity expressive challenger, Gemini 3.8 Flash-Lite as the volume workhorse, and the best rights-cleared open models as free/self-hosted options. Select a specific voice only after the Vietnamese and English blind-review tracks pass separately.



### Eleven v4 matched marketplace benchmark

The manual workflow, ElevenLabs Eleven v4 marketplace quality benchmark, selects the most-used eligible high_quality/professional public shared voices for Vietnamese and/or English, then generates matched audition passages using the Eleven v4 model. It is capped at four voice IDs per language and eight synthesis requests per run. Every selected voice uses the same corpus in its language; the output is normalized, VoiceStudio-watermarked and machine-validated.

The workflow runs only when the repository is private, ELEVENLABS_API_KEY exists, and confirm_paid_api_usage=true is explicitly selected. It uploads a blind listening archive separately from the private analysis mapping. Human reviewers score naturalness, pronunciation, prosody, emotional fit, accent fit and overall preference. The discovery counters determine which voices are auditioned first; they never count as quality scores. An ambiguous POST timeout is not retried automatically because provider-side acceptance and billing may already have occurred.

Run it from Actions → ElevenLabs Eleven v4 marketplace quality benchmark. Start with the default two voices per language; review the blind package before increasing the offset for later batches. This workflow is disabled on public repositories and is never run automatically by CI.



### Turning blind listening into a ranked voice set

After listeners complete `blind-review.html` and export the CSV, keep the matching `analysis.json` artifact private and merge the two files:

```bash
python scripts/merge_elevenlabs_v4_blind_scores.py \
  --analysis dist/elevenlabs-v4-benchmark/analysis.json \
  --scores eleven-v4-blind-review.csv \
  --output dist/elevenlabs-v4-benchmark/scored-analysis.json \
  --summary-csv dist/elevenlabs-v4-benchmark/voice-rankings.csv
```

The merger supports multiple reviewers per blind sample, rejects duplicate reviewer/sample pairs, unknown IDs, language mismatches, incomplete score rows, and values outside the 1–5 scale. It returns separate VI and EN rankings with average naturalness, pronunciation, prosody, emotion, accent-fit and overall preference. Blank template rows are ignored. These cohort-specific human ratings are not standardized MOS and should never be interpreted without review counts; they do not clear voice rights or prove universal listener preference.

Blind audio and private voice mapping must remain in separate artifacts until scores have been submitted. Do not upload the mapping to a public issue, discussion, or public artifact.


### Google Gemini prebuilt voice discovery

VoiceStudio also indexes the Google Gemini Voices API using `GET /v1beta/voices`. Google exposes voice metadata such as language code, region, accent, persona, context, gender and pitch, and paginates the response with a page token (up to 1,000 voices per page).

The crawler is deliberately restricted to `type=prebuilt` and language prefixes `vi` and `en`. The API can also return `prompted` and `replicated` voices; those may be caller-owned or custom voices, so they are excluded from the shared discovery catalog. The ListVoices result does not include sample audio for prebuilt voices; this workflow therefore generates no audio and does not claim to audition the voices.

- Use Gemini 3.8 Flash TTS as the high-fidelity, expressive provider candidate.
- Use Gemini 3.8 Flash-Lite TTS as the throughput-oriented candidate.
- Treat the returned voice IDs as Google-managed identifiers, not audio files that VoiceStudio may redistribute.
- Keep Google API use and model-generated audio subject to current plan, data-use and commercial terms. No TTS generation is performed by this metadata workflow.
- The weekly Actions workflow requires the read-only GEMINI_API_KEY secret. If it is absent, the run records a setup note and skips discovery rather than failing the repository CI.

This catalog is a metadata index, not a count of verified voice quality. A voice must still pass matched VI/EN listening, locale pronunciation, long-form stability and authorized commercial-use review before being recommended for a particular production.



### Gemini 3.8 Flash TTS and Flash-Lite matched voice benchmark

Google publishes 30 official prebuilt studio voice options and a separate Extended Voice Library with hundreds of additional provider-managed options. The static 30-option index is stored in `voice-library/gemini-prebuilt-studio-voices.json`; the dynamic metadata crawler reads `GET /v1beta/voices` and filters to prebuilt Vietnamese/English records. Gemini's catalog metadata does not contain usage counts comparable to the ElevenLabs marketplace, so VoiceStudio does not label these options popular or rank them by adoption.

The manual workflow, Gemini 3.8 prebuilt voice quality benchmark, tests one model per run:
- `gemini-3.8-flash-tts` is the high-fidelity expressive candidate.
- `gemini-3.8-flash-lite-tts` is the throughput-oriented candidate.

Each run refreshes the provider voice metadata, selects up to four voices per language (eight requests maximum), and uses the same four-scenario text corpus: story, numbers, conversation and long-form narration. Every voice receives the same style instruction for each matched passage in its language. Output is normalized to 48 kHz/24-bit, VoiceStudio-watermarked, validated, and placed in a blind-listening archive separate from the voice-ID mapping.

The workflow requires a private repository, `GEMINI_API_KEY`, and explicit `confirm_paid_api_usage=true`. It is manual-only, disabled on this public fork, and never triggered by normal CI. Run it once for each model with the same offset/limit to compare Flash vs Flash-Lite fairly. An ambiguous request timeout is not retried automatically.

The score-merger keeps model IDs separate when ranking the same voice ID across providers or model variants. Scores are human preference for this review cohort, not standardized MOS. This workflow uses prebuilt provider voices only; it does not replicate named people or expose caller-owned prompted/replicated voices.


### Building a large original voice-actor catalogue

To scale beyond provider-owned presets, VoiceStudio now defines a privacy-first contribution contract for original voices from adult contributors (18+) who are themselves the recorded speaker. The manifest schema is `voice-library/voice-contribution.schema.json`; the validator is `scripts/validate_voice_contribution.py`; intake policy is in `voice-library/contributions/README.md`.

The contract separates permissions instead of assuming a single blanket release:
- TTS synthesis and voice replication.
- Commercial use.
- Public previews and public distribution.
- Model training.
- Derivative voice generation.

The latter four remain separate opt-ins. A contribution cannot become production-ready until rights review and native-language quality review both pass. The validator also rejects personal identifiers and public audio URLs in manifests. Only pseudonymous contributor IDs, opaque private-vault references and consent hashes may live in public Git; signed records, identity checks and raw audio remain in private storage.

The intake directory currently contains policy only, not real contributors or ready-to-use voice assets. The objective is to recruit original, consenting adult voice actors across Vietnamese regional accents and English locales, then build toward hundreds or thousands only at the pace that review, withdrawal and rights management can support. Never reproduce a celebrity, creator or other identifiable person's voice without authorization from that exact person.
