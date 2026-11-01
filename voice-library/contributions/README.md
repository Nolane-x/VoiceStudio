# Voice contribution intake

This directory accepts **metadata-only, pseudonymous manifests** for original voices contributed by the recorded speaker. It is the path toward scaling the library with real, independently contributed voices rather than copying recognizable voices without permission.

## Non-negotiable intake rules

- Contributors must be adults (18+) and the recorded speaker must be the contributor.
- The contributor must explicitly approve voice synthesis and voice replication. Commercial use, public previews, public distribution, model training and derivative voice generation are separate opt-ins.
- Never clone a celebrity, creator, public figure, colleague, family member or other identifiable person unless that exact speaker has explicitly authorized the specific use.
- A marketplace listing, public upload, dataset license or model-card license is not by itself proof that the speaker consented to synthesis, cloning, model training or commercial distribution.
- The original recording, signed consent record, identity verification and withdrawal contact live in a private, access-controlled vault. Never commit these files, contact details, legal names, signatures, raw voice audio, presigned URLs or private storage URLs to this repository.
- Public manifests contain only opaque references (asset_… and vault_…) and a hash of the private consent record. These references must not be reversible into a person's identity by public users.
- Model-training and derivative-generation permission remain off unless explicitly selected. Permission to synthesize a voice does not imply permission to train a model on its recordings.

## Review and production gate

1. Confirm adult status and that the speaker is the contributor using a private process.
2. Collect a separate, versioned consent record that describes every requested use and the withdrawal process.
3. Store the original audio and signed record privately; create a pseudonymous manifest.
4. Review recording provenance and the exact permissions granted.
5. Run Vietnamese/English native-language listening, pronunciation, long-form stability, clipping, noise, and watermark checks.
6. Mark the manifest production_ready=true only after the rights and quality reviews are both approved and the required rights are explicitly granted.

Run the validator:

~~~bash
python scripts/validate_voice_contribution.py
python scripts/validate_voice_contribution.py path/to/contribution.json
~~~

The validator checks the JSON schema and cross-field consent/production rules. It does not verify the legal identity, authenticity of signatures, recording ownership, or actual audio quality; those are private human-review responsibilities.

## Suggested scale-up strategy

Start with a small pilot of 10–20 adult contributors across northern, central and southern Vietnamese accents plus a balanced English set. Keep at least two independent reviewers for each language before promoting any voice. Build toward hundreds or thousands only as consent records, storage, deletion/withdrawal handling, quality review and commercial permissions can be maintained per contributor.

No personal data or audio should be committed in this folder. Put only approved pseudonymous JSON manifests here.
