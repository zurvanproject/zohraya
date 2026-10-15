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
