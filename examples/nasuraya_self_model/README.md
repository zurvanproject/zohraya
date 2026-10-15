# Evidence-linked functional self-model

This opt-in layer asks a narrow self-knowledge question: **when I request this
action, does my existing software body actually admit it?** It keeps observed
body state, inferred self-efficacy, unknowns, requested actions and native effects
separate. It does not measure subjective experience.

The native physiological predictor and the unmerged adaptive predictor in PR #3
already exist. This layer adds prospective admission estimates, explicit
abstention and a goal gate; it does not replace either predictor. No native
equations, identity principles, model weights or existing checkpoints change.

## Learn only from a verified effect

```python
from examples.nasuraya_self_model.monitor import SelfModel, snapshot

model = SelfModel.create('/private/new-self-model.sqlite')
prediction = model.begin(body, exact_native_request)  # persists BEFORE action
receipt = body.cycle(**exact_native_request)
result = model.finish(exact_native_request['event_id'], body, receipt)
report = model.inspect(snapshot(body), next_native_request)
```

`finish` accepts only the body's cached matching receipt, request hash, next
revision, source identity, journal predecessor and conservation audit. A late
prediction, unrelated receipt or conflicting replay rejects. An unresolved
outcome prevents new learning past it. Duplicate completion does not learn twice.
The model history is reconstructed and checked on load, including predictions,
scores, labels and counts. Hashes detect damage, not malicious host rewrites.

The estimate is `(successes + 1) / (samples + 2)`, a Beta(1,1) mean for the
observed software admission outcome. It is not globally calibrated. Contexts
separate body/controller source, action, duration, posture, coarse sleep/fatigue/
pain regimes and supplied input conditions. Sensor values, modality, declared
kind and freshness remain distinct; sample IDs and absolute timestamps do not.
These are coarse engineering contexts, not exhaustive body/world models.

## Let self-knowledge affect execution

```python
from examples.nasuraya_self_model.goal_bridge import step_goal, reconcile_goal

result = step_goal(model, motion_journal)
# result['executed'] is False when evidence/experience is insufficient.
# A pending prediction may be completed only from a verified native receipt:
reconcile_goal(model, motion_journal)
```

Unknown or fewer than three context samples, stale body evidence, unresolved
outcomes, native read-out restrictions or admission estimate below 0.7 pause the
tick. Pausing issues no native command and spends no motion-goal budget. An
allowed tick still passes through the original MotionJournal and native guards.
There is no autonomous exploration or new action grant. Initial training probes
are explicit experimental actions, not decisions attributed to this gate.

## Reproduce

From the repository root:

```
python3 -m unittest examples.nasuraya_self_model.test_monitor examples.nasuraya_self_model.test_goal_bridge -v
python3 -m examples.nasuraya_self_model.evaluate evaluate --output /private/NEW-evaluation
python3 -m examples.nasuraya_self_model.evaluate practice --source /private/advanced_goal.json --output /private/NEW-practice
```

`protocol.json` freezes eight training and four held-out native fixture inputs
before measurement. Held-out receipts are scored without changing model counts.
The comparator is an uninformed fixed 0.5 admission estimate, not the native
analytical forecast, PR #3 or a general intelligent agent. Native starting
checkpoint hashes are disjoint. A fresh Python process must restore the exact
same model history. This is a small designed software test, not a broad claim
of calibration or increased subjective awareness.

The practice driver copies an existing accumulated MotionGoal, observes before
each of four authorized probes, records predictions before outcomes and learns
from committed native receipts. It demonstrates the gate before and after
practice and saves the advanced goal plus the self-model. Private inputs and
generated states stay outside Git. Nothing starts running in the background.

## Choose a bounded next action while retaining the goal

`regulation.py` adds an opt-in session around an existing accumulated
`MotionGoal`. It retains the route, goal ID, native clock, energy, fatigue,
landing history and all remaining motion budgets. A session permits at most
12 owner ticks, three observations and three recovery requests. Its default
subgoal is one additional confirmed landing; reaching that subgoal pauses the
session without declaring the full route complete.

Before each owner tick it inspects the saved self-model and simulates the
available walk, observe and rest/sleep requests on private copies of the whole
body. These counterfactuals do not advance the owner. A fixed policy prefers
bounded recovery for current body need, one observation for an uncertain
context, then a move admitted by the fresh native forecast. Weak historical
admission estimates alone need not leave the goal permanently paused. Only the
actual native receipt updates the session's knowledge. The selected predicted
receipt must exactly match the owner receipt. This is same-model planning,
not an independent physical measurement or learned action-selection policy.

Every deliberate observation/recovery spends one second from the original
phase budget. Such requests preserve the current walk-veto streak; only an
admitted walk clears it. Three actual vetoes of intended walks still close the
route. The 220-second route limit and native action guards remain in force.
When no valid candidate fits the remaining budgets, execution stops with a
recorded block; it does not force a movement request.

`RegulationJournal` uses the existing durable motion intent/outcome protocol.
A repeated committed event returns its stored receipt. A complete saved outcome
can be verified and published without any native simulation or execution;
an intent with no verifiable outcome remains blocked. The generic journal now
accepts a goal wrapper; ordinary `MotionGoal` remains its default.

```
python3 -m unittest examples.nasuraya_self_model.test_regulation -v
python3 -m examples.nasuraya_self_model.run_regulation start --source /private/advanced_goal.json --model /private/self_model.sqlite --max-ticks 12 --output /private/NEW-regulation
```

The driver copies the private inputs, commits two decisions, terminates that
worker with exit code 75, then resumes in a fresh Python worker. The saved
SQLite journal, decisions and final session preserve the next continuation.
The input files remain unchanged. Session learning is retained inside that
session; it does not overwrite the input self-model database. No live model API
or official body-state publication is part of this driver.
