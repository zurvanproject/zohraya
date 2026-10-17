# Progress, cost and correction on the retained goal

`PlanningGoal` continues an existing `MotionGoal` through its remaining route
and closure. Its tick allowance is exactly `230 - initial_elapsed`: no phase
budget, body clock, fuel stock, fatigue, goal ID or landing history is reset.
The previous admission self-model remains available. Three observations and
three recovery requests bound the whole continuation, without per-landing refill.

At a plan boundary, the planner compares up to 16 seconds of walking, one
observation followed by walking, and up to two rest/sleep ticks followed by
walking. It stops each projection at the next predicted confirmed touchdown.
Plans are refreshed when their series ends, a real landing occurs, the goal
changes phase, a body need calls for recovery, or native arbitration vetoes the
requested action. Current high sleep pressure, fatigue or pain can take priority
over progress. Optional observation is restricted to double support/settling.

## Forecast scope and continuity

Projections use private copies of the retained physiological/mechanical owner
kernel. They omit future arbitration and the evolving outer modules and affect
loop; they are approximate same-model predictions, not actual owner actions.
Canonical owner restoration plus the original controller overlay precedes
projection. This matters: a regression found different projections from a warm
owner and a restored owner despite equal actual receipts. Canonical projection
now makes warm/cold planning agree. Native equations and controller files stay
unchanged.

Every actual action still runs through `UnifiedBody.cycle()`. Shared
`advance_motion()` preserves the existing regulated goal bookkeeping, confirmed
touchdown cursor, three-walk-veto closure and original route/closure time limits.
It was factored out of the previous regulator without changing its selection.

## Learn from returned outcomes

Before execution, a plan saves its predicted landing time, cumulative fuel,
fatigue and landing count. Each committed native tick records its real receipt,
state and prospective errors. A fixed 0.25 exponential correction updates
bounded per-action fuel/fatigue biases. A real touchdown settles **all** earlier
forecasts for that next touchdown, including expired plans; absence of a
touchdown never becomes a fabricated zero timing error. ETA corrections are
bounded to eight seconds.

The next plan ranks valid candidates by corrected ETA, corrected fuel cost
(`0.001 seconds/J`) and projected fatigue above 0.52. These weights are explicit
engineering choices. Correction uses past completed receipts only. A synthetic
regression demonstrates an observed forecast error changing the next selection.
Actual-run summaries separately report whether choices or only estimates changed.

Admission counts update from the verified first receipt of each plan, where a
full source-pinned self-observation exists. Other tick receipts still teach cost
corrections and remain in the session history. This is local session learning;
the input self-model database and conversational model weights are not rewritten.

## Persistence and execution

`PlanningJournal` retains the existing durable intent/outcome protocol. Duplicate
tokens return stored receipts. An unknown action outcome blocks continuation.
A complete durable outcome reuses its saved plan and is verified without native
execution or fresh projections. An optional process-local `current_goal` avoids
redundant restores only after comparing its **complete checkpoint** to the
committed state under the owner lock. A stale or modified cache rejects.

```
python3 -m unittest examples.nasuraya_self_model.test_planning -v
python3 -m examples.nasuraya_self_model.run_planning start --seed /private/seed.json --output /private/NEW-planning
python3 -m examples.nasuraya_self_model.run_planning control --seed /private/seed.json --output /private/NEW-control
```

The start driver commits through landing 12, terminates with exit code 75, then
continues in a fresh worker through route termination and required closure.
The control executes the identical planner without interruption. Compare the
entire final envelope, not only a next tick. Summary prediction errors are
prequential measurements on this one trajectory; ETA forecasts overlap, and
these figures are not a held-out general benchmark.

The private seed was exported with the previous pinned code before this
refactor: restore the prior `RegulatedGoal`, retain `old.goal.checkpoint()` and
`old.derived()[0]`, and record the prior envelope/file SHA and commit. It is an
explicit lossless planning-layer attachment, with no native body execution.
Old regulated checkpoints require their original source version. Private body
files and experiment outputs are retained outside Git. This driver publishes
no official body state and invokes no live model API.
