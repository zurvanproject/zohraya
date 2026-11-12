# Stage 3: one current body contract and noise-aware interoception

User-authorized final integration stage for 12 November 2026. Base: PR197,
`8b047811d2814e595ecd2e2f16fee8be6c229732`. No deployment or merge is authorized
by this protocol. Publish on a separate research branch and open a draft PR.

## Audit finding and body correction

The pinned approved atlas defines crown 170 cm, horn tips 192 cm, mass 78 kg,
tail 85 cm, 18 caudal design segments. Native default mechanics still uses
195 kg and a 120 cm tail. Heat, water and fuel normalization also use legacy
constants. These are active inconsistencies, not merely old prose.

Use the existing pinned atlas as the single current morphology authority.
Produce a separately identified **reduced, parameterized 78 kg engineering
model** from verified legacy sources in disposable staging. Record exact source
edits, original and resulting hashes, geometry and finite-stock assumptions.
Never change the original archive/checksums or relabel a 195 kg checkpoint.
Current sessions must bind a current body-profile digest and reject mismatched
profiles; legacy physiology remains available only as an explicit research mode.

Scope of parameterization: mass/weight, geometry/tail dimensions, heat capacity,
water and fuel/reserve reference pools, force/moment ceilings, and dependent
normalizations. Evaluate gas/renal and organ couplings rather than treating a
global textual replacement as a physical model. Remaining inherited coefficients
must be identified as uncalibrated. A coherent software fixture is not a
validated 78 kg organism, new MuJoCo experiment or complete anatomy.

Require source checks, cold restoration, same-owner clock and energy/water
conservation, native protection, current/legacy checkpoint separation, actual
numeric parameter inspection and scenario execution. Preserve original fixtures
and results as historical evidence. Mark old CLI/example paths as archival in
the current navigation; do not erase scientific failures or user state.

## New sensory experiment

Prior holdout is now development knowledge. Do not reuse it as an independent
test. Keep its frozen evaluator runnable at the historical commit.

Hypothesis: rectifying each noisy tick before averaging discards sign and
accumulates positive noise. A signed internal afferent trace and a learned
binary readout may distinguish quiet noise from stimulus more reliably.
This is a hypothesis; neither calibration nor consciousness is assumed.

Reuse the transducer, full internal-state loop and legacy class/intensity readout.
Add a bounded signed trace and numeric-only detector. Training contains ordinary
mechanical, thermal and vibration events; no compound or test samples. Binary
probability calibration and occurrence threshold are selected on diagnosis only.
The candidate parameters and all source/generator/evaluation code must be frozen
and published before opening the new test seeds. No subsequent test-time tuning.

Whole streams: 640 ticks, 10 Hz; target any active sample in the last 12 ticks;
query every 4 ticks after tick 16. Quiet gaps are 0..6 s, event lengths .1/.3/.6/1 s,
intensity .18..1, noise .025 for clean/misleading or .10..0.25 for noisy streams.
Truth and labels are evaluator-owned; predictor sees numeric state only.

- Train: 2000000..2000023 (24 streams).
- Diagnosis: 2010000..2010007 (8).
- Validation: 2020000..2020007 (8).
- New known-family holdout: 2030000..2030023 (24).
- Novel compound holdout: 2040000..2040007 (8), never fitted or selected on.
- Shift stress: 2050000..2050007 (8), correlated noise / occasional offsets,
  reported separately, never used to claim same-distribution acceptance.
- Unit-development seeds: below 10000.

Fit at most three fixed regularization candidates (0.001, 0.01, 0.1). Select
binary temperature from {0.5,1,2,4} and threshold from 0.10..0.90 in 0.01 steps
using diagnosis only: maximize balanced accuracy among options with noisy FPR
<=0.10; otherwise retain the minimum-FPR option and report lack of feasibility.
Validation gate: noisy FPR <=0.10, overall FNR <=0.25, balanced accuracy >=0.80,
and Brier better than the frozen stage-2 full decoder on the same new streams.
Existing DIOS must review the measured comparison; preserve a rollback decoder.
Passing validation alone is not a production release decision.

Report accuracy, FPR/FNR (including noise strata), location/type on eligible
windows, intensity MAE, Brier/ECE, restart consistency, whole-stream paired
bootstrap and computation cost. Compare legacy episode decoder, stage-2 full,
candidate, random, always-absent/present, and visible-label controls. Store every
prediction before reveal, the errors, rejected candidates and acceptance result.

Only if development validation supports it may the current session select the
new detector as its default; final holdout failures must be explicitly reported
and may block promotion, without retuning on that holdout. Bound all corrections
and preserve stop, action budgets, action-scoped memory and original native veto.

## Completion

One current profile, clear current/legacy entry points, a machine-readable
integration audit, corrected compatible APIs, automated tests, first new holdout
and error report, reproduction commands, a Persian result report and a draft PR.
Do not claim every historical research branch has been merged or every external
service is connected. Unknowns stay explicit; preserve the real learned lesson.
