# Fixed enriched-input and weight-update evidence

48 new training receipts (24 ADMIT, 24 DEFER) supported exactly 96 balanced
LoRA choice-loss steps. All 61,440 trainable values changed across 16 tensors;
all 8 effective attention matrices changed; frozen base tensor hashes agree.
The earlier v0.3 42 outcomes are development evidence, not the new 40-case test.

All seven final prediction sets were persisted before the first test outcome.
Every fixed request was probed irrespective of prediction. No threshold, prompt,
training length or hyperparameter was adjusted using these test outcomes.

- Calibrated parent / legacy input: 40/40, no false admissions.
- Frozen choice / legacy input: 24/40, 16 false admissions.
- Frozen choice / enriched input: 38/40, 2 false admissions.
- Trained choice / enriched input: 38/40, the SAME 2 false admissions.
- Audit preflight: 38/40; constant ADMIT: 18/40; constant DEFER: 22/40.

Thus input format improves the frozen model on these cases; additional weight
updates do not improve decision accuracy over the frozen/enriched control.
Brier decreases from 0.145238 to 0.048309, but the two wrong zero/zero-friction
admissions become more confident (about 0.65 to 0.98). Native selection is
slow_breath in both. The calibrated parent is better; promotion fails and no
advisor binding changes. No claim of numeric grounding or general superiority.
Audit restriction words remain an available shortcut. Pain varies only in
forefoot_L; exposing three other regions does not demonstrate transfer to them.

All eight intermediate/asymmetric-friction cases admit and all eight mixed
cases defer; balanced accuracy is null for these single-class families. These
are authored source-pinned software fixtures, not independent real-world data.
The first unit suite caught invalid draft durations before dataset preparation;
the corrected combined suite passes 30 tests. All 72 tracked native files match
the parent. Full plans, receipt SQLite and all three real adapter states are
private. Reduced rows carry checkpoint/receipt hashes and pre-action features.

Cold restoration reloads the three adapter states for four model/input pairs,
verifies 88 receipt-derived rows, recomputes metrics/promotion and reproduces
scores without network, optimizer steps, body cycles or duplicate learning.
