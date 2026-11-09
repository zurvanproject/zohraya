# DIOS v1 | دیوس: Image Preflight for Tadash

Transparent and auditable local preflight for image generation requests. A PASS_LOCAL result is not provider approval. This module never circumvents moderation, does not inspect pixels, and does not submit images or prompts automatically.

## Workflow

Request + optional image reference -> Persian/English normalization -> conservative local rule assessment (PASS_LOCAL / REVIEW / BLOCK) -> authorized human or vision review -> independent image provider decision -> feedback -> observational statistics.

## Quick start (Python 3.10+, no external dependencies)

    python -m unittest discover -s examples/nasuraya_image_preflight -v
    python -m examples.nasuraya_image_preflight --db .dios/audit.sqlite3 check --input examples/nasuraya_image_preflight/request-example.json
    python -m examples.nasuraya_image_preflight --db .dios/audit.sqlite3 check --prompt 'ناسورایا با نامه فارسی در باغ'

To use an actual reference image, add --reference-file PATH. A SHA-256 is computed; no pixels are parsed. The resulting gate is REVIEW unless the reference was genuinely assessed. In that case use --human-reviewed and the accurate --subject-kind, --rights-confirmed, and --age-assessed options. These CLI flags are attestations, not cryptographic proof, and cannot be trusted from untrusted users in a public API.

## Feedback

    python -m examples.nasuraya_image_preflight --db .dios/audit.sqlite3 feedback --request-id REQUEST_ID --provider image-provider --outcome accepted
    python -m examples.nasuraya_image_preflight --db .dios/audit.sqlite3 stats --provider image-provider

Accepted, policy_rejected, and technical_error are recorded separately. Technical errors never count as moderation outcomes. Rates and Wilson 95% intervals appear only after 20 actual valid observations per local verdict and provider. The observations may be selection-biased and do not constitute knowledge of provider internals.

## Deployment boundaries

The SQLite ledger stores SHA-256 fingerprints, verdicts, findings, and feedback; not original prompts, private photos, or generated outputs. Before server use: add an authorized pixel-inspecting vision adapter with trusted provenance, authentication, tenant segregation, encryption at rest, rate limits, and retention policy. Keep provider moderation final. Do not automatically resubmit refused material. Add independently sampled, consented benchmark datasets to estimate false negatives and false positives. Keyword rules alone are not a validated, general-purpose safety model.

DIOS v1 is an isolated prototype, intentionally not coupled to the existing Tadash runtimes.
