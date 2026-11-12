# Stage 2: continuous streams and bounded reconsideration

Stacked on the shared session in PR196. Read the
[first holdout results](../../docs/research/NASURAYA_STAGE2_RESULTS_2026-11-12_FA.md)
before opting in. Continuous occurrence Brier improved, but accuracy did not;
noisy quiet-window false positives remain very high. Neither decoder is validated
as a reliable continuous noise detector. No production rollout is justified.

## Reproduce

Python 3.11+, standard library, repository root; choose new output directories.

```bash
python -m unittest examples.nasuraya_runtime.test_session examples.nasuraya_runtime.test_stage2 -v
python -m unittest examples.tadash_interoception.test_interoception -v
python -m unittest discover -s examples/dios_nous -v
python -m unittest discover -s examples/nasuraya_agent_loop/tests -v
# Linux only: the inherited bootstrap verifies and stages native source files.
python -m examples.nasuraya_body_loop test
python -m scripts.verify_nasuraya_stage2 --output /tmp/stage2-regression
python -m examples.nasuraya_runtime.reconsideration_demo --output /tmp/stage2-reconsideration
```

The regression compares all held-out categorical predictions exactly, numeric
values with absolute tolerance 1e-10 / relative 1e-9, and ignores execution time.
It audits the hash chain, prediction-before-truth ordering and state commitments
inside each transcript. Cross-version byte-level state-hash differences are
reported separately; within-run cold-state consistency is still required.
This repeats already-opened data, not another prospective test or new evidence
of generalization. Frozen source/model identity is enforced before generation.

To regenerate development in a new directory, without overwriting the artifact:

```bash
python -m examples.nasuraya_runtime.stream_study develop --output /tmp/stage2-development
python -m examples.nasuraya_runtime.stream_study test --frozen docs/evidence/nasuraya-stage2-v01/frozen-models.json.gz --output /tmp/stage2-test-repeat
```

Do not fit new parameters to these test seeds and describe the resulting scores
as held-out. The frozen package retains baseline, candidate, selected model and
validation acceptance for full, no-memory and no-attention variants. All three
selected temperatures were 1.0; the observed change is mostly fitting to a new
continuous training distribution, not evidence of autonomous general learning.

## Session API

```bash
python -m examples.nasuraya_runtime create --session /tmp/stage2-workshop --decoder continuous_v1 --max-actions 8
# Linux: opt in separately to evidence-bound native reconsideration.
python -m examples.nasuraya_runtime create --session /tmp/stage2-native --backend native --fixture transient_pain --decoder continuous_v1 --reconsider --max-actions 8
```

`Session.create(..., decoder_version='continuous_v1', reconsideration=True)`
offers the same options in Python. Existing `step`, `snapshot` and `stop` APIs
are unchanged. Input is a tuple of 1–16 numeric `AfferentFrame`s at consecutive
0.1 s ticks, with an expected revision. The continuous decoder's first step must
contain at least 12 frames; an incomplete initial history fails atomically.
It estimates occurrence during the last 12 ticks, not occurrence at a single
instant. There is no fitting or truth ingress inside the session.

Snapshots expose decoder version, uncertainty scope, retry policy and retained
blocks. Receipts expose the evidence review, distinct observations, hypothetical
preflight and actual outcome. Numerical pressure still drives the existing
authored action policy; improved probability calibration alone does not establish
better task utility. The native demo isolates retry policy and uses the default
legacy decoder so that changed classifier fitting does not confound that comparison.

Reconsideration requires a known native blocking cause, two fresh owned safe
observations (energy >=.35, fatigue <=.42, pain <=.30, sleep <=.75), and a preflight
that selects walk from the same native checkpoint. The real body always decides
the executed action. An unknown cause stays blocked. A forecast is not an observed
success; action-specific DIOS evidence changes only after the actual receipt.

Defaults remain `decoder_version='legacy'`, `reconsideration=False`. Schema is now
`nasuraya.shared-session/2`. Existing v1 sessions fail closed and require their
original code or a future explicit migration. For rollback, start a new session
with the retained legacy model/policy; do not edit a live checkpoint's config.
The transient fixture declares a one-time nociceptive initialization, then lets
the original native equations evolve it. No later manual pain reset occurs.

This is a bounded local simulator. Native Linux runtime remains 195 kg; no new
anatomical, physical, server, consciousness or live provider claim is made.
