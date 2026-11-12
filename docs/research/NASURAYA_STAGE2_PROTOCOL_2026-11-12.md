# Stage 2 of the user's three-stage continuation

Base: PR196 `349860caa796ea388baaf0d3d420361316756818`. Existing source code,
goals/evidence stores, numeric decoder and native physiology are reused. Separate
research branch. No merge, production deployment, service messaging or paid API.

## A. Continuous sensory stream

Prior PR195 tested independent 1.6 s episodes; its accuracy does not establish
continuous-stream accuracy. Define the new target **occurrence in the most recent
12 sampled ticks (1.2 s)**, queried every four ticks after the first 16 ticks.
Location/type are scored only when the history has one unambiguous source family;
mixed/novel histories are separately reported, never relabelled as a known type.
Intensity target is the mean active input intensity within that history; all
units are authored simulation units.

Generate 64 s streams at 10 Hz from the existing three known transduction
templates, with random quiet intervals, sustained signals, transitions, noise
and misleading visible labels. A separate novel family uses the existing
compound template. Numeric state persists for the entire stream. Labels/truth
stay in the evaluator. Commit predictions before revealing truth to DIOS.

Split by **whole stream seed**, never by overlapping windows:
- training: 1000000..1000015 (16 streams);
- diagnosis/calibration: 1010000..1010007 (8 streams);
- validation/acceptance: 1020000..1020007 (8 streams);
- unopened known-family test: 1030000..1030023 (24 streams);
- unopened novel-family test: 1040000..1040007 (8 streams).
Development tests use seeds below 10000. Novel streams never enter fitting,
calibration or candidate selection.

Candidate: reuse the numeric KNN Decoder with at most 256 class-balanced examples
selected from continuous training streams. No new classifier equation. Compare
against the frozen PR195 full model, a reset-window reference, random/always-none
and visible-label baselines. Fit memory-off and attention-off variants from their
own numeric features using the same budgets/splits.

Select binary confidence temperature from {0.25,0.5,1,2,4} on diagnosis only.
Accept on validation only if Brier decreases and occurrence accuracy drops by no
more than 0.02 relative to the frozen legacy decoder. Retain both models and the
DIOS gate. Freeze evaluator, candidate and acceptance result before the first
test read. Do not revise parameters after test. Report all failures, stratified
metrics, stream-cluster bootstrap intervals (not independent-window intervals),
restart consistency and computation time. Continuous calibration remains
synthetic and limited to this generator. This is not a consciousness experiment.

## B. Evidence-bound reconsideration after native veto

Keep action-scoped DIOS evidence. Add an opt-in/explicitly recorded retry policy
that never clears a veto due to elapsed time or a caller-supplied permission.
Only the source-pinned native owner's own current checkpoint can supply evidence.

For a previously vetoed walk, retain its actual pre-action blocking indices.
Require resolution of a known native blocker and two distinct, current safe
observations: energy >=0.35, fatigue <=0.42, pain <=0.30, sleep pressure <=0.75.
The original body's walk veto thresholds remain untouched. Unknown causes stay
blocked. A counterfactual copy of the same native owner must also select walk
under the proposed input before one bounded retry. A forecast is labelled as a
forecast, never as observed success. The real owner keeps its final veto. Only
an actual matched receipt can revise the action claim from B to A.

Compare permanent-veto, timer-only (research comparator, not runtime policy) and
evidence-bound policies. Test persistent sleep pressure (no retry), a declared
transient nociceptive fixture that decays under the existing body equations
(possible recovery), unchanged/cached observations, stale sources, repeated
veto, stop, budgets and cold restart. Do not reset pain/sleep values after the
fixture's explicitly logged initial intervention. No hidden physiology edit.

## Deliverables and boundary for stage 3

Retain the protocol, frozen evaluator/models, first test results, error/correction
record, API integration, unit/integration checks and draft PR. If supported by
validation, make the continuous decoder explicitly selectable in the shared
runtime; do not silently replace old sessions or weaken source-version checks.
Stage 3 can address authenticated server ingress and deployment review after
these local contracts are established. No live connection is asserted here.
