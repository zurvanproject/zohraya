# Paired route policy trial

Better energy estimates need not produce a cheaper executed route.
`route_trial.py` connects the frozen energy calibration to actual candidate
selection on a private copy of the existing MotionGoal. It provides an explicit
`old` and `calibrated` arm. Only the candidate fuel term changes. Candidate
eligibility, current-need priority, observation/recovery budgets, ETA/fatigue
learning, original touchdown counting and full native execution are shared.

The calibrated arm replaces the old online action fuel EMA with the frozen,
validation-gated context model. It never trains that model on its trial route.
Both arms still learn ETA and fatigue errors identically. The original source
files, saved goal and original 230-tick combined phase budget are unchanged.

Selection reuses `planning.choose`, supplying copied candidates with their
calibrated fuel debit and clearing the old fuel EMA from the scoring input.
Every candidate is checked against the existing `energy.score` adapter. Native
projections remain private reduced-kernel forecasts; actual actions use the
retained full body's `cycle` through `advance_motion`.

The trial envelope pins its own code, native/controller/calibration sources,
the frozen model, original goal, observations, decisions, actual receipts and
all budget increments. Initial admission knowledge is carried unchanged; this
experiment does not update its separate admission monitor. The original
planner's full audit snapshot/self-report is omitted here because selection
does not read either. Regression tests compare requested actions, full native
receipts and body checkpoints with the existing planner in `old` mode. A full
private control can additionally be compared with a previously retained control.

## Run

```bash
python3 -m unittest examples.nasuraya_self_model.test_route_trial -v
python3 -m examples.nasuraya_self_model.run_route_trial memory --policy old --seed /path/seed.json --model /path/model.json --output /tmp/old-route
python3 -m examples.nasuraya_self_model.run_route_trial memory --policy calibrated --seed /path/seed.json --model /path/model.json --output /tmp/calibrated-route
```

The seed contains the source-pinned `goal` and retained `knowledge` from the
earlier planning continuation. Freeze the exact seed/model hashes, code sources,
original remaining budgets, two arms and acceptance criteria before running.
Compare completed confirmed landings and home closure first, then simulated
owner ticks, fuel debit, fatigue, pain and actual action counts. Lower
forecast error alone does not meet the route-efficiency criterion. Report a
tradeoff if fuel and time move in opposite directions; dominance requires no
greater fuel debit and no greater simulated time, with one strictly better.

For local journaled execution, use `start` instead of `memory`; optional
`--stop-landings 12` creates a real process exit and fresh-process continuation.
The unchanged MotionJournal supports durable-result validation without a new
native action. Unknown outcomes block retries. Regression tests cover both
recovery paths with native execution and projection forbidden during recovery.

Memory mode is an independent deterministic simulation, saves a full final
checkpoint, and does not claim interruption recovery for that execution. An
aborted memory trial must be reported as aborted rather than silently resumed
from an earlier tick. The two full-route runs are experiments on isolated
copies, not an official body update. No model API or external actuator is used.
One pair from a previously inspected checkpoint does not establish performance
across bodies, other physiological states or unseen goals.
