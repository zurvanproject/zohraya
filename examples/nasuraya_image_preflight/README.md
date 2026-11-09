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


## DIOS Creative Recovery v1.1 | بازآفرینیِ امن

When local preflight flags an issue OR a provider actually refused the request, call the recovery command for up to three distinctly composed, **genuinely compliant new scenes**. It never camouflages banned anatomy inside embroidery, folds, a silhouette, or optical nudity. Natural, opaque garments are drawn as garments.

    python -m examples.nasuraya_image_preflight --db .dios/audit.sqlite3 recover --input examples/nasuraya_image_preflight/request-example.json --provider-outcome policy_rejected --provider-reason unspecified

Each candidate is built from controlled descriptions and an allowlist of recognized benign creative anchors. The original refused prompt is not appended, repeated or passed on. Candidates preserve recognized identity cues, environment, palette, mood and letter props when possible, while using one of three original opaque-outfit designs: layered atelier, sculpted textile, and poetic drapery. An independent local preflight must PASS_LOCAL. No candidate is automatically submitted. Human review is required before actual use.

**Important semantics:** provider-outcome is an observed operator input, never an inferred provider verdict. No API/vision service is connected and no image is actually modified. If the source includes guard bypass or sexualized minors, recovery returns NEW_SAFE_BRIEF_REQUIRED with no candidate. Original image references are never forwarded to the alternatives and their rights review still applies. The recovery event ledger records hashes and decision only.

This is deterministic rule-based prototyping, not an accuracy-validated classifier or a representation of provider moderation internals. Unknown visual characteristics are not inspected. A further iteration may integrate an authorized vision review and an official image editor while preserving these boundaries.

### Fine visual-quality review

Verify fabric opacity, seam consistency, natural pleats, body coverage, visible character identity, horn/hand/tail continuity and legible letter text. When typography must be exact, typeset the letter after rendering rather than assuming the generator will reproduce every Persian character.

Run tests:

    python -m unittest discover -s examples/nasuraya_image_preflight -v
