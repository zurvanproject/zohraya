# Stage 3: a single current body and explicit research limits

Current entry point: `python -m examples.nasuraya_runtime`, Python 3.11+,
standard library; native backend requires Linux. No credentials or live provider.
See the [prospective protocol](../../docs/research/NASURAYA_STAGE3_PROTOCOL_2026-11-12.md)
and [Persian results](../../docs/research/NASURAYA_STAGE3_RESULTS_2026-11-12_FA.md).

## One authority, separate histories

`profile.current()` reads `CANONICAL_TARGET` from the existing verified full-body
atlas pinned by DIOS. No competing morphology file is introduced.

| Property | Current contract | Archived native fixture |
|---|---:|---:|
| Crown height, cm | 170 | 250 |
| Horn-tip height, cm | 192 | 266 in neutral executable pose |
| Mass, kg | 78 | 195 |
| Tail centreline, cm | 85 | 120 |
| Reference water, L | 44 | 110 |
| Reference fuel, J | 1,600,000 | 4,000,000 |
| Reference reserve, J | 24,000 | 60,000 |
| Heat capacity proxy, J/K | 273,000 | 682,500 |

The current model ID is `tadash_reduced_78kg_v1`. The native worker first verifies
all 70 recovered original source files, copies them, and applies exact checked
edits **before importing the native kernel**. Its receipt contains each edit's
match count and before/after hash. Source archive, saved user states and old
evidence are unchanged. Source-bound checkpoints reject cross-profile restore.

The parameterization covers mass/weight, reduced joint geometry, tail, extensive
stocks and gas thresholds, resource normalization, renal reference pools, force
and moment ceilings, and related balance normalization. It scales extensive
quantities linearly, not through empirically fitted allometry. The point-contact
foot patches, controller gains, tissues and pressure proxies remain engineering
assumptions. This is neither a new MuJoCo run nor complete physiological calibration.
The nominal 18 caudal design segments are not 18 newly simulated vertebrae.

New sessions default to this current body. `create --legacy-body` explicitly
selects `tadash_legacy_195kg` for historical research. The older standalone
`nasuraya_body_loop` CLI is also historical. The current inventory identifies
exactly one native default. The separate 78 kg MuJoCo lineage is catalogued and
was not rerun or merged. Schema 1/2 sessions require their historical code; this
change refuses implicit migration and never resets them.

## Sensory state and correction

Schema 3 retains the existing sensory state and a bounded 64-tick signed trace.
Occurrence features use the last 12 ticks and an internally estimated noise
floor. No truth labels, timestamps of event boundaries, simulator seeds or direct
stimulus instructions reach the decoder. A first signed/continuous decision
requires at least 12 observed ticks in one submission; subsequent submissions
may contain 1–16 ticks. Short first submissions fail without committing state.

The signed candidate uses a trained logistic occurrence readout. Class/intensity
still use the original stage-2 decoder. When occurrence is detected without a
class assignment, the report says unknown and marks uncertainty. Probability
calibration measures occurrence, not calibrated confidence for the whole report.

The three-run cycle is baseline, diagnosis/development, then frozen held-out
execution. DIOS records predictions before truth, records every error and reviews
the correction. The strict noisy FPR acceptance ceiling is 10%. Validation was
**rejected** (28/266 = 10.53%); the candidate cannot be selected as `noise_v1`.
`noise_candidate` is an explicitly labelled research option. Default `legacy`
remains unchanged; neither it nor `continuous_v1` is qualified for robust noise.
The experiment's `selected` comparator means stage-2 fallback, not the runtime
default. No held-out data tunes parameters, thresholds or acceptance criteria.

When explicitly selected, the signed probability modulates an authored action
pressure and native touch projection. That is an executed policy link, not a
learned optimum or proven utility gain. Original DIOS evidence, action-specific
dissent, optional `--reconsider`, goal/budget persistence, native final veto and
stop remain active. Native action selection and physical touchdown/displacement
are reported separately; requesting a walk does not establish completed walking.

## Run and reproduce

Use a new output directory each time, from the repository root:

```bash
python -m examples.nasuraya_runtime.audit --output /tmp/current-integration-audit.json
python -m unittest examples.nasuraya_runtime.test_session examples.nasuraya_runtime.test_stage2 examples.nasuraya_runtime.test_stage3 -v
python -m examples.nasuraya_runtime.body_demo --output /tmp/stage3-body
python -m examples.nasuraya_runtime demo --native --output /tmp/stage3-shared
python -m scripts.verify_nasuraya_stage3 --output /tmp/stage3-regression
python -m examples.nasuraya_runtime create --session /tmp/stage3-research --backend native --decoder noise_candidate --reconsider
```

`body_demo` compares normal/sleep fixtures across both body profiles, including
cold repeat, actual contact outcomes and conservation. `verify_nasuraya_stage3`
replays already-opened data with frozen source/model hashes, checks all categorical
predictions exactly, numeric predictions within 1e-10 absolute/1e-9 relative
cross-Python tolerance, and independently audits the prediction-before-truth chain.
Timing is reported, not compared. It never trains; it is not another independent test.

To reproduce development only:

```bash
python -m examples.nasuraya_runtime.noise_study develop --output /tmp/stage3-development
```

For the original stage-2 experiment use its [historical checkout](STAGE2.md).
Do not edit frozen source hashes to make historical evidence appear current.
No server, Moltbook, desktop, live model provider or external actuator was joined
by this stage. Genome remains a fixed fixture, visual output remains text planning,
and ritual progress remains a pinned reference. See `audit.py` for the machine-
readable distinction between implemented connections and executed observations.
