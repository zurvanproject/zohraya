# Independent closed-loop evaluation v0.2

This stage evaluates the unchanged v0.1 prediction algorithm on broader synthetic regimes. It adds a test-only frozen-policy harness; the v0.1 learning constants, native body equations, action permissions and the API bridge are unchanged.

## What is actually different

The v0.1 held-out comparison supplied a shared executed transition to two frozen predictors and scored shadow recommendations. Here each arm has its own locked BodyLoop database, independently chooses an action, and actually invokes the existing DecisionCore/ReflectiveBody/UnifiedBody pipeline. Each case begins from an identical checkpoint for A and B; each arm receives up to three permitted action slots and the same scheduled native fixture inputs. A uses a fixed zero-delta persistence predictor; B uses the local parameters recovered from verified native training. Both retain the v0.1 conservative prediction-based selection policy.

Learning constants and prediction equations stay unchanged; a physical-validity guard was repaired after the diagnostic. Training consists of the unchanged eight normal and four sleep transitions per arm. The verified normal/guarded parameter buckets are combined only when keys do not overlap; all original safety and learning constants stay fixed. Evaluation models are immutable. Every case is a new explicitly journaled synthetic sleep-pressure/muscle-tone fixture, optionally warmed up by existing `walk` cycles before the trial. Warm-up construction is identical for both arms and is reported separately from the three-action goal budget. Initial five-state/posture fingerprints are checked for split disjointness.

Two validation cases and six final cases cover standing, ongoing motion, high sleep pressure, a pain episode in the retained forefoot atlas, a native impulse and low friction. Perturbations are the existing native runtime's inputs, not new tools or actuators. Their precommitted payloads occur during action two and are intentionally withheld from the predictor's state-only input until their consequences are observed. The fixture schedule is not a real sensor stream or an authenticated physical producer.

## Fair measurement when actions differ

Own-path forecast MAEs are descriptive: arm A and B can execute different actions and thus observe different outcomes. They cannot establish a causal forecast advantage. The controlled forecasting endpoint evaluates **both** frozen models on every executed transition from **both** arms, using the same before-state, requested preference and observed native outcome for each comparison. The initial diagnostic supplied 36 paired final transitions, without changing either model. Results include per-case native/core overrides, realized walks, unknown prediction contexts, physical model validity, and exceedances of the empirical residual envelope.

Decision correctness is matching the existing fixed self-maintenance contract on each arm's observed pre-action state. It is not a claim of optimal decisions. In particular, the fixed persistence baseline always has unknown-context uncertainty and is conservative about walking; a better score than that baseline does not show superiority to the original fixed `SelfMaintenance` policy or the native analytical lookahead. No strong-baseline or biological performance claim is made.

## Durable frozen trials

The immutable model, verified-training source locators, scenario and initial checkpoint are stored in a hashed contract. Each intent stores the observed state, chosen preference, frozen prediction, ordinal and exact scheduled native perturbation before execution. The native engine commits its existing receipt/checkpoint atomically; the test harness then stores the measured result. Every reported result and policy choice is recomputed from the native receipt and frozen model on verification. An invalid native physical model aborts the remaining trial and preserves unused budget. The production adaptive learner now also rejects such outcomes rather than updating its parameters. Each arm closes after one cycle and completes its own trajectory in a fresh interpreter. A further completed replay must leave all body state and action budgets unchanged.

A pending action with no completed native receipt is blocked rather than reexecuted. A committed native action is reconciled once. Tampering, incompatible contracts, unauthorized fixture fields, nonfinite inputs, external body changes and body budget exhaustion fail closed. Identity continuity is verified before and after every step. The test harness is exposed only by the fixed benchmark CLI, not as an arbitrary production API/agent tool.

## Reproduction

```bash
python3 -m examples.nasuraya_body_loop closed-loop-test
python3 -m examples.nasuraya_body_loop closed-loop-benchmark --output-dir /tmp/closed-new
python3 -m examples.nasuraya_body_loop adaptive-test
python3 -m examples.nasuraya_body_loop test
```

Use a new output directory. No API key or model service is needed. The verified worker strips the key. The dedicated GitHub Actions workflow reproduces the frozen trial and integrity checks, and checks truthful reporting even when the aggregate MAE fails to improve.

## Scope and next decision

This is a small deterministic computational evaluation, with three 0.1-second decisions per arm. Empirical envelopes are not calibrated or guaranteed confidence intervals. Unknown disturbance inputs can dominate forecast error. A positive aggregate difference alone does not establish robust generalization: review each perturbed regime, physical validity and envelope exceedance separately. The initial moving fixtures and after-perturbation functional states are retained in the machine report rather than assumed from their labels.

The immediate next priority is tracing the native physical invalidity under pain and verifying a valid protective response against its exact native receipt. A stronger fixed-maintenance/analytical baseline and explicit disturbance handling remain subsequent evaluation needs. Do not tune this predictor or declare a new independent test using the final outcomes from this protocol.

## Diagnostic failure and safety repair

The original precommitted diagnostic improved paired aggregate MAE by only 0.2663% (0.0187103018437 to 0.0186604835585). Low friction made the adaptive forecast worse on the paired case. The pain case set the native physical-model-validity flag false on two consecutive outcomes in each arm; adaptive residual envelopes were exceeded once in pain and once in impulse. The original production learner checked conservation but did not reject the independent physical-validity flag.

The guard was repaired without modifying body equations or predictive parameters: invalid physical outcomes cannot train AdaptiveMemory, and the frozen test trial stops after the first invalid outcome. The pre-repair report and protocol are retained as diagnostic evidence. The post-repair run replays already examined scenarios to verify stopping and retention; it is **not another independent test**. Aggregate forecast improvement and stress acceptance are reported separately. Overall success requires both; the known stress failures therefore remain a negative result. CI validates correct execution and honest reporting, rather than demanding a favorable experiment result.

## Measured repair verification

| Endpoint | Fixed A | Adaptive B |
| --- | ---: | ---: |
| Paired MAE on both actual paths | 0.01980742048598522 | 0.019754671713394057 |
| Actual preferences matching declared contract | 3 | 17 |
| Actual cycles | 17 | 17 |
| Physical invalid outcomes before abort | 1 | 1 |
| Empirical envelope exceedances | 0 | 2 |

The repair replay has 34 paired final transitions and 0.2663% MAE reduction. Overall stress acceptance is **false**, despite positive forecast-only reduction. In the pain case both arms stop after two cycles, retain one action, and do not continue the physically invalid trajectory. This is repair verification on already examined data, not new independent evidence.

98 related tests passed without skips: 12 closed-loop/safety, 19 adaptive, 26 body/identity and 41 controlled API/recovery. Sixteen independent trajectory restarts and completed/blocked replays preserve models, native effects and budgets. The native body source files are unchanged. Evidence and the original diagnostic are under examples/nasuraya_body_loop/evidence/closed_v02/.
