# Decision relevance and a prospective state survey

The previous private route reduced one-tick fuel-estimate MAE without changing
any of its 32 plan choices. `decision_relevance.py` now records the distinction
before an actual action: whether costs changed, whether the winning admissible
choice changed, and whether a current body need or required goal phase determined
the choice. Each candidate also reports corrected, unseen, sparse and
validation-withheld forecast steps. Coverage refers to the existing coarse
context cells, not a guarantee for a new physiological domain.

The diagnostic is read-only. It pins code and model, preserves scores and
choices, and can be recomputed from the saved pre-action plan. It neither trains
the calibration nor executes the native body. A changed score is never labeled
as measured behavioral benefit.

`decision_survey_protocol.json` freezes 16 fresh synthetic states: four declared
uniform channel-fatigue initial conditions, two sleep-pressure conditions and
both route directions. Initial fatigue is explicitly assigned and recorded as
an external initial-condition construction; it is not represented as paid work
or a reset of private user state. The unchanged six-tick prelude then evolves
each body natively. Every case, including guards and failures, is retained.

Both existing RouteTrial policies run up to 32 policy ticks from the exact same
case checkpoint. Policy weights, guards and original MotionGoal budgets stay
unchanged. The energy model is frozen. The first two cases in protocol order
with different requested-action traces receive followup, irrespective of their
fuel outcomes. This conditional selection is not a population benefit estimate.

Followup stops at four confirmed landings, original termination or 64 total
policy ticks, then applies up to four paid slow-breath pause ticks. These ticks
are charged through `advance_motion` to the original goal counters. The original
14-point route and its pending targets remain stored. A prefix-efficiency claim
requires both endpoints to have exactly four landings, the same grounded feet,
double support, no active swing and valid native receipts. Fuel and simulated
time include the pause. Different progress or unstable endpoints cannot be
counted as a win. No full-route completion/efficiency claim follows from this
bounded experiment.

`NoSafeChoice` is recorded as a resolved safety refusal before an action. The
owner hash must stay unchanged, the complete trial is saved, and a later call
cannot prepare or execute another tick after that halt. Followup applies no
pause action to a halted arm. This differs from an unknown action outcome;
neither case authorizes a retry. Each measurement epoch gives fresh synthetic
goals unique IDs; a failed earlier in-memory measurement is retained as aborted
and is not represented as recovered execution.

```bash
python3 -m unittest examples.nasuraya_self_model.test_decision_relevance -v
python3 -m examples.nasuraya_self_model.run_decision_survey --model /path/model.json --output /tmp/new-survey --workers 4
python3 -m examples.nasuraya_self_model.run_decision_survey --model /path/model.json --output /tmp/new-survey --audit
```

The audit can run in a fresh process with native execution and new rollouts
forbidden. It restores source-pinned goals, recomputes every saved decision
assessment, checks the frozen followup selection, verifies available native
pause receipts and preserves the remaining original targets. The survey uses
isolated in-memory simulations and does not claim mid-action crash recovery for
them. An existing output directory blocks an accidental full-run retry. The
original journal's unknown-outcome rules remain unchanged.

The cohort is deterministic and correlated through a common native kernel;
distinct pressure values or checkpoint hashes do not establish independent
energy trajectories. The audit reports distinct executed traces. The original
private body, native source equations, calibration and earlier checkpoint
schemas are unchanged. No live model API or external actuator is used.
