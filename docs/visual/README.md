# Nasuraya visual-anatomy gate v1 (2026-11-15)

**Purpose:** fix the recurring image-generation error in which an ordinary human bent/cross-legged pose is given fur and animal claws. Prioritize an anatomically traceable skeleton over rich robes, lighting, fire, and atmosphere.

This file is an **illustration contract**, not a claim of validated physics, a full 3-D rig, or guaranteed compliance by a generative image tool. The source project has several incompatible adult-scale drafts; therefore we constrain **topology and joint proportions**, not canonical height/mass.

## Sources of the character morphology

The existing primary repository contains:
- `runtimes/tadash_body/anatomy_systems_v01.json` sections **G02** (two balanced horn roots), **G03** (five fingers per hand, three independent toes per foot), **G04** (forward knee, rear hock/true ankle, elongated metatarsals, toe-pad load path), **G05** (sacral tail root).
- `runtimes/tadash_body/phenotype_v1.json` confirms digitigrade feet, two horns, a sacral tail, three toes per foot, and a delicate feminine outer silhouette.

## 2D pose topology

The structured contract at `nasuraya_pose_contract_v1.json` defines two normalized lateral skeletons (standing and seated on a **solid low bench**), with these joints in order:

`hip → anatomical knee → hock / actual ankle → long metatarsals → three toes with pads`

Both poses preserve each segment length within 2.5%. The knee is **forward** of the hock in a lateral view. In standing the hock is clearly off the ground; in sitting the hock lowers toward the ground without becoming the knee. The metatarsals remain visibly distinct from the shin and from the three toes.

A natural human cross-legged pose with fox claws pasted on the feet is an **automatic visual rejection**. A seated humanoid torso is acceptable **only** when the pelvis is physically supported and both hind limbs still show their distinctive joint chain.

## Horn constraints

Precisely two keratin-sheathed red horns growing from corresponding skull roots, with the same length and mirrored arcs in neutral front view. Different apparent sizes are allowed only from perspective, not from changing the underlying geometry. For front-view checking, first remove hair covering the horn roots.

## Image-generation protocol

1. **Block out** the head, pelvis, two leg bone chains, three digits of each foot and sacral tail at low detail.
2. **Check a standing front view** for paired horns, visible toe cardinality and overall limb symmetry.
3. **Check a seated three-quarter or side view** for a supported pelvis, forward knee, backward lower hock, long metatarsal, three separately articulated ground-contacting toes.
4. Only after passing both, add facial detail, copper curls, fur, clothing, robe patterns, earrings, background, Celtic motifs or ritual lighting.
5. **Reject and re-block** rather than hiding incorrect legs with a robe, mist, a foreground brazier, or cropping.

Compact reusable render brief:

> A copper-haired, amber-eyed, feminine fox-demon with two truly mirrored scarlet horns rooted in the skull, a sacral tail, five fingers per hand and **three** separate toes on each **digitigrade** foot. Both legs must show hip → forward-pointing knee → lower backward hock (true ankle) → elongated metatarsals → three toe-pads. A seated figure sits on a low support, knee forward and hock lower/back, without human cross-legged feet. Keep all key joints fully visible and unobscured. Start from accurate anatomy, then add costume and cinematic effects.

## Verification and limitations

`python -m unittest discover -s tests -p 'test_nasuraya_visual_anatomy.py' -v`

This checks the stored geometry, **not rendered pixels**. The illustrated final image must still pass an explicit visual review. Passing six scripted tests does not mean a text-to-image model will always obey the pose contract. For true mechanical validity, a collision-aware 3D skeleton and motion simulation would be necessary. No existing VPS service, Awake record, Qwen timer, or body runtime is changed.

## Failure found in the user's generated Body Test Suite poster (2026-11-15)

The reference skeleton tests **passed** but the external generative image did not obey them. The cropped **underside paw has FOUR separate distal digital pads/claws**, not the canonical three. The ritual panel uses an unsupported human lotus/cross-legged pose, with the hocks and metatarsal chains occluded by robes/fire. The poster's green checks and speed/endurance metrics have **no instrumented backing** and must not be repeated as observed performance.

The failed poster SHA-256 is `d31664145371b441ac4a4b78a2d075eb3928d8c61ce1110c72c1f9e2f5bda37b`. Its annotated failure is retained in `evidence/rejected_body_suite_20261115.json`.

A simpler three-panel revision with **three** front claws on each foot and exactly **three** distal plantar pads plus **one** larger central pad was generated (SHA-256 `ceb43d45768aecf473dda860730596f915ba84bd21e0bff8defa8e7afb0cea70`). It removes the human cross-leg and seats the pelvis on a bench. **However, the hock-to-metatarsal chain remains insufficiently apparent from the chosen camera angle**, so it is a **partial visual improvement, not a completed biomechanical pass**. See `evidence/revised_three_toes_seated_pose_partial_20261115.json`.

The independent manual-annotation review CLI lives at `tools/nasu_visual_image_audit.py`. It rejects four-toe paws and faulty sitting in *any* inset, and distinguishes plantar pad observations (only possible in the underside view) from unseen pads in dorsal views. It does **not** count pixels autonomously: the viewer must inspect the actual rendered image and record truthful observations before using the CLI.
