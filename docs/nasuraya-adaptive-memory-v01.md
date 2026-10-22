# NASURAYA: Adaptive Memory & Predictive Self-Model v0.1

This adds an offline local predictor to the recovered synthetic UnifiedBody, its existing DecisionCore/ReflectionCycle bridge, and IdentityContinuity. Native source-pinned equations, API interfaces and action permissions are unchanged. The only requested actions are `walk` and `observe`; native protection may realize `protect`.

## Before and after

Before: source-linked observations → fixed self-maintenance preference → DecisionCore → native body/veto → persistent receipt. The prior paired benchmark measured a one-veto difference on two manually specified fixtures, not predictive parameter learning.

After: observe → forecast → fixed predictive safety policy → existing DecisionCore → native body → validate native receipt/audits → compute prediction error → atomically commit experience and a model version → next bounded decision. Completed native outcomes can be recovered without replay. Missing/unknown outcomes block all new adaptive execution.

## Local model contract

The predictor forecasts five normalized indices (`energy`, `fatigue`, `sleep_pressure`, `pain`, `balance`) for one **0.1-second** synthetic cycle. Current functional posture, fixed safety classification, requested action, and verified action/outcome history select a bucket. Each bucket holds sample count, a five-dimensional delta, maximum observed pre-update absolute residuals and categorical realized-action counts. Unsupported contexts retain the current state and report unknown action and uncertainty 1.

For each field, after validating a native outcome:

`delta_new = clip(0.5 * delta_old + 0.5 * clip(observed_after - observed_before, -0.1, 0.1), -0.1, 0.1)`

`prediction = clip(current + delta, 0, 1)`

Residual envelopes have a fixed 0.005 floor and never shrink below historical errors. They are engineering uncertainty indicators, **not calibrated probabilities or guaranteed bounds**. Modal realized-action counts are descriptive evidence, not calibrated categorical probabilities. Three consecutive MAEs above 0.05 prevent a walk recommendation. Unknown context, residual envelope above 0.05, unfavorable predicted state or a predicted veto also switch the fixed goal policy to observation. Explicit stress/training schedules remain separately identified experimental contracts and still pass through DecisionCore and native vetoes.

Learning is exclusively from the existing locked local native ledger: completed execution, matching before-checkpoint/action/duration evidence and passing energy, water, light and same-owner-tick audits. Caller-supplied `verified=True` or a model's success statement is not an accepted learning interface. This does not authenticate an external sensor producer.

## Persistence and identity

`nasu_experiences` stores the complete observed before-state, action, goal/reason, fixed safety-plan evidence, frozen prediction, native outcome, signed and absolute errors, MAE, provenance and model versions. `nasu_predictor_versions` stores bounded model revisions with reason, source, parent hash and frozen constitutional principles. All parameter revisions are recomputed from the corresponding verified experience during integrity checking. Reversion appends a new source-linked version; it never deletes history.

The pre-action intent is durable before execution. The already atomic native checkpoint/receipt commit precedes a second atomic transaction containing learning and the completed experience. A crash between the two is reconciled from the native receipt. A crash inside learning rolls back both the model update and completed experience. A pending intent without a completed native receipt is never reexecuted automatically, including when it may actually have stopped before execution.

Identity is verified before predictions, learning and action. Empty existing identity/model history fails closed rather than silently initializing. Belief names cannot shadow any constitutional principle. Hashes detect corruption and missing provenance; they do not prevent a malicious rewrite of the whole database or source code.

## Bounded execution

An explicit goal follows 1–3 cycles without another user message. Goal IDs retain their exact contracts, including target and time budget, across restart. No new goal is selected by the software. The existing body action budget is 0–100; adaptive storage is limited to 256 experiences, 256 goals, 512 model versions and 64 parameter buckets. The runner checks a 1–60 second invocation time budget before each action; the verified CLI additionally kills the worker after 60 seconds. An interrupted native operation remains subject to existing recovery rules. Time limits restart per invocation, while action/goal budgets remain durable. No daemon or external actuator is included.

## Reproduce without credentials

```bash
python3 runtimes/tadash_body/run_tests.py --reflection --output /tmp/native-new
python3 -m examples.nasuraya_body_loop test
python3 -m examples.nasuraya_body_loop adaptive-test
python3 -m examples.nasuraya_body_loop predictive-benchmark --output-dir /tmp/predictive-new
python3 -m examples.nasuraya_body_loop start --session /tmp/adaptive-new.sqlite --max-actions 3
python3 -m examples.nasuraya_body_loop adaptive --session /tmp/adaptive-new.sqlite --goal-id authorized-test --target-cycles 2
python3 -m examples.nasuraya_body_loop adaptive --session /tmp/adaptive-new.sqlite --goal-id authorized-test --target-cycles 2
```

Use fresh output/session paths. Ordinary adaptive commands strip `OPENAI_API_KEY`; none calls an external model. Optional existing SDK transport tests use mocked/controlled HTTP transports only.

## Evaluation design and limits

A and B receive identical verified training receipts from independently initialized native bodies, the same requested action schedule and the same action budgets. A records experiences without parameter learning; B updates its local EMA. Both use the same fixed recommendation policy; only B has trained local parameters. Twelve training transitions precede three validation and six final test transitions. Validation and test start from new, explicitly journaled synthetic sleep-pressure interventions. Five-state/posture/action fingerprints are checked for split disjointness. The learned models are frozen during both evaluation splits, whose native action schedules are identical for paired forecasting. A shared held-out execution supplies the same observed outcome to both frozen predictors.

The recommendation correctness metric compares **shadow recommendations** against the existing fixed self-maintenance contract, not separate closed-loop action trajectories or independent evidence of optimal decisions. Native veto counts are measured on the common execution schedule; no comparative veto improvement is claimed for this evaluation. Cold recovery starts a new interpreter and compares full parameters, versions, cycles and remaining budgets.

An initial evaluation draft overlapped training inputs; its result was discarded. `rejected_draft_protocol.json` preserves that draft for review. Only the corrected disjoint protocol is accepted; the algorithm and its learning/safety constants were not tuned against final outcomes. These small related deterministic trajectories provide limited synthetic acceptance evidence, not a blinded benchmark, biological forecast, model-weight training, general intelligence or subjective awareness.

See `examples/nasuraya_body_loop/evidence/adaptive_v01/` for measured results and test logs. The next priority is an additional precommitted evaluation spanning new functional/postural regimes and abrupt but explicitly journaled interventions, with separate closed-loop decision trajectories and thresholds held fixed.

## Measured local results

| Measure | A: fixed | B: adaptive |
| --- | ---: | ---: |
| validation MAE, five normalized indices | 6.87237134366e-05 | 1.54612246802e-05 |
| validation shadow recommendations matching fixed contract | 1/3 | 3/3 |
| test MAE, five normalized indices | 6.39030854806e-05 | 1.7069062533e-05 |
| test shadow recommendations matching fixed contract | 2/6 | 6/6 |

Accepted final-test MAE reduction: **73.29%**. Absolute changes are small over the short prediction horizon. All shared held-out executions had zero native vetoes and exact declared action budgets. Four cold model recovery checks passed; frozen parameters were unchanged during validation/test. The earlier draft is excluded.

248 distinct unit/regression tests passed with zero skips in the complete SDK-supported run: 99 native/core, 26 existing body/identity, 41 body API/recovery using controlled transports, 60 agent/SDK, 3 motion mirror and 19 new adaptive tests. The existing 484-state grid had zero violations; the 12 native scenario suite and prior paired benchmark reproduced. No paid/live model request was issued.

The CLI cold-goal smoke test completed two cycles, recovered model version 3 with one action remaining, and returned the exact same result in a new invocation. Real worker processes terminated with os._exit during learning, after native commit and after intent; tests verified rollback, receipt-only recovery and blocking unknown effects respectively.
