# Validation-gated energy calibration

The progress planner's 57-tick continuation completed its route, but its
per-request EMA raised energy MAE from 72.58 to 79.90 J/tick. Requested `walk`
pooled different physical phases and native vetoes. A correction learned in one
phase could therefore worsen the next phase's estimate.

`energy.py` adds an explicitly versioned alternative. It uses requested action,
observed and projected posture, forecast age, and the existing sleep/fatigue/pain
thresholds. Every feature is available before the action. Native selection and
actual fuel debit are outcome labels only; vetoed requests are retained rather
than silently removed. A context requires three training outcomes. Its median
residual is shrunk by half and limited to 250 J. Two separate validation outcomes
must show at least 5% lower absolute error before the correction is enabled.
Unseen, sparse and failed-validation contexts use the raw forecast.

Training, validation and frozen stages are irreversible. Frozen models cannot
learn. Duplicate event IDs cannot teach twice. Checksummed checkpoints pin the
forecaster, calibration policy, controller and native Python/JSON sources;
fixture-generated defaults are excluded. A new process can finish the same
training/validation sequence and obtain an identical final model.

The original `planning.py`, `MotionGoal`, native equations and journal are
unchanged, preserving existing checkpoints. `energy.score` is an explicit
opt-in adapter that replaces only the old fuel correction in candidate cost.
It preserves ETA/fatigue terms. Its future contexts use predicted states, not
future actual observations. The existing `PlanningGoal` does not automatically
adopt it: improved one-tick estimates do not establish better route choices.

## Reproduce

```bash
python3 -m unittest examples.nasuraya_self_model.test_energy -v
python3 -m examples.nasuraya_self_model.evaluate_energy evaluate --output /tmp/energy-new
python3 -m examples.nasuraya_self_model.evaluate_energy reanalyze --output /tmp/energy-new
```

`energy_protocol.json` fixes four training, two validation, and three held-out
synthetic native fixtures with disjoint declared sleep-pressure values. Each
gets the original six prelude ticks, then up to 24 original requested actions.
Forecasts refresh after observed touchdowns, vetoes, phase changes or exhaustion.
Both comparators use the same saved reduced-kernel forecasts and actual native
receipts. The old EMA is trained on the training split and frozen before test,
as is the new calibration; validation gates only the new correction. The full
original body's completed goal is never advanced by this evaluation.

The report includes all fixture results, not just admitted walks. Acceptance
requires held-out energy MAE below both raw and old EMA, an unchanged held-out
model, and identical predictions in a fresh process. `reanalyze` validates source
pinned initial/final goals, receipt lineage and available native receipt copies,
then reproduces learning and metrics without executing native actions. Existing
prediction values and fitted parameters must agree. This allows a checkpoint
contract to add source fingerprints without changing shared fingerprints or the learned estimates; any earlier
contract is retained as `prior_model_contract.json`.

The separate `transfer` command can score a previously inspected PlanningGoal
checkpoint without advancing it. Such a check is retrospective and is reported
separately from the synthetic held-out split.

This is a deterministic software fixture evaluation of one-tick energy debit.
Nearby sleep-pressure fixtures share a native kernel and are correlated. No
claim of unseen morphology, private-body calibration, physical-body validity,
better whole-route choices, or live API execution follows from these results.

## Measured run, 15 October 2026

Nine fixtures produced 199 measured post-prelude ticks: 96 training, 48
validation and 55 held-out. Held-out MAE was 66.4587 J raw, 102.8048 J with the
frozen old EMA, and 48.3383 J with gated calibration (27.27% below raw). Only
38 of 55 predictions received a correction. The high-pressure fixture used raw
fallback throughout and stopped normally after three native vetoes and closure.
The two ordinary held-out fixtures had identical energy traces, leaving two
distinct held-out energy traces; these are not 55 independent experiments.
Frozen predictions matched exactly in a fresh process and held-out learning
was disabled.

Retrospective transfer to the previously inspected 57-tick private trajectory
gave 60.4440 J MAE versus 72.5839 J raw and 79.8988 J old prequential EMA.
This transfer check advanced no native actions and preserved the original goal
hash. It is supporting retrospective evidence, not another blind test.
