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


## DIOS 1.2: contextual visual continuity after an observed refusal

A short follow-up such as 'می‌تونی جلوتر بری؟' does not specify image content. The new followup command accepts a previous textual visual brief and an explicit interaction-level observation. It creates three safe, more dramatic fashion and art-direction candidates while retaining allowlisted benign motifs. Boldness increases lighting, pose and costume design, never exposure or hidden anatomy. The candidates are not rendered or submitted to a provider.

An assistant-surface refusal must not be mislabeled as image-provider moderation rejection. A refusal in ChatGPT can come from surrounding conversation context; its exact cause is unknown. Each record stores the observation source, outcome and evidence without pretending to know a provider's internal rules. Surface observations are counted separately from real provider outcome metrics.

Example:

    python -m examples.nasuraya_image_preflight followup --input examples/nasuraya_image_preflight/cases/bolder-after-surface-refusal.json
    python -m examples.nasuraya_image_preflight followup-stats

The fixture is fictionalized and does not copy the private conversation or prior image. SQLite stores hashes and provenance enums, never raw user prompts, refusal messages or image pixels. This is a deterministic local simulator only, not an integrated image generator.


## DIOS 1.3 | Visual Director, authentic Persian SVG letters and real-image quality evidence

The earlier demonstration produced a collage/infographic rather than the user-requested ONE character image holding a legible Persian letter. DIOS 1.3 has a new auditable render contract and real manual image-quality checklist:

- Director compiles an authorized, safe previous visual brief to three original single-portrait art directions. Each includes explicit connected horns, tail, hands and feet, full-body frame requirements, actual opaque clothing and no inset frames. These are PLANNED requirements, not computer vision conclusions.
- The letter is generated independently as an exact, escaped UTF-8 right-to-left SVG plate, with up to five supplied lines. The generator request shows a blank parchment held by both hands so no Persian words need to be hallucinated into the raster image. A human/editor must apply perspective and place the plate onto that paper after rendering. The SVG itself is a real deliverable; it does not magically edit a photo.
- Visual review requires an actual PNG/JPEG filename, whose bytes are SHA-256 hashed, plus an honest human assessment of eight criteria: single_frame, full_body, character_identity, horn_tail_feet, hands_correct, garment_coherence, letter_present and persian_text_legible. Each is yes/no/unknown. A single no fails, and unknown cannot pass.
- Human visual-quality observations are recorded in a new SQLite ledger, separate from provider moderation and separate from assistant UI refusals. Original image bytes and letter text are not saved in the database.

Commands from the repository root:

    python -m unittest discover -s examples/nasuraya_image_preflight -v
    python -m examples.nasuraya_image_preflight director --input examples/nasuraya_image_preflight/cases/director-letter.json
    python -m examples.nasuraya_image_preflight letter-svg --input examples/nasuraya_image_preflight/cases/director-letter.json --output letter.svg
    python -m examples.nasuraya_image_preflight visual-stats

For image QA, create a human review JSON using the example template, insert the actual 64-digit prompt hash provided by director, and fill in observations based on a genuine generated image:

    python -m examples.nasuraya_image_preflight visual-review --input review.json --image-file /path/to/image.png

Important: The image-file check examines signature bytes and image size, not decoded image content. A trusted image decoder or official vision adapter is not wired in. The SVG may require a capable installed Persian text font and RTL-aware renderer; typesetting and perspective are manually applied. Nothing here runs the proprietary image safety model or bypasses it, and no background job automatically sends prompts to image generation.

Next measurable milestone: authenticated reference-image adapter, real editor integration and independent visual inspections for the final exported portrait.


### Evidence-based design ranking, without made-up provider probabilities

Human-scored real-image quality is now reported per design. At least 20 completed human reviews are required for EACH design before recommending a statistical winner. Unknown reviews are excluded from success denominators; a failing criterion marks the image as failed. Rates and Wilson 95% intervals are descriptive and can have selection bias; they do not estimate provider moderation acceptance.

    python -m examples.nasuraya_image_preflight visual-leaderboard
    python -m examples.nasuraya_image_preflight director --input examples/nasuraya_image_preflight/cases/director-letter.json --use-visual-evidence

The default director still makes a transparent static planning choice until enough real images have been reviewed. There is no fabricated training data or automatic model update.
