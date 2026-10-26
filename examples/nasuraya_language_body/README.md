# Body-informed local language weights v0.4

The frozen v0.3 primary adapter falsely admitted six fatigue/pain requests even
though the native owner protected itself. This experiment gives the local model
more complete pre-action inputs, performs real fixed-budget LoRA updates, and
measures paired decisions against new native receipts. It changes the local
61,440-parameter adapter, not ChatGPT or the live API model. Native mechanics,
identity, user body state and existing advisor binding remain unchanged.

## Input and scope

`data.features()` reads observed aggregate fatigue and perceived pain, left/right
leg fatigue, four named slow-pain foot regions, duration, sleep pressure, current
audit restriction words and supplied per-foot friction (native default 0.6).
Regional slow pain is a software proxy, not injury or a clinical dose. Friction
is a declared simulation input, not a sensor measurement. Features are read
before the requested action; receipt fields are excluded. Text keeps four
decimal places, so this is not an arbitrary-precision numeric interface.

Only forefoot_L is varied in the authored pain fixtures. The other three foot
regions are explicitly exposed but have no trained regional-transfer claim.
All samples share one source-pinned synthetic body generator. Initialization
uses the v0.3 declared-stock/sensory-cache correction, without inventing a new
sensor frame, exertion or healing history. Other initial state is retained.

## Fixed experiment

Before any new labels, `protocol.json` and source hashes fix 48 training cases,
40 test cases, disjoint sleep pressures and durations, 96 balanced choice-loss
steps, seed, learning rate, scoring and promotion rule. Native durations must
align to 0.1-second ticks: train 0.2/0.4 s, test 0.6/0.9 s. An initial unit test
caught invalid draft durations before preparation or training; the failure is
retained. No held-out labels influence prompts, thresholds or training length.
The earlier 42 transfer outcomes are development evidence, not this test.

The primary model starts from the frozen choice_balanced adapter. Only new,
receipt-validated training rows reach its optimizer. The study also evaluates:

- the original parent with its previously frozen legacy-input threshold;
- the frozen choice adapter on legacy inputs;
- the same frozen choice adapter on enriched inputs;
- audit preflight and both constant-label comparators.

The frozen/enriched versus trained/enriched comparison isolates the effect of
weight updates for this fixed input format. The frozen legacy/enriched pair
measures the input-format change without updating weights. This does not by
itself establish numeric grounding: audit restriction words remain available.

All seven sets of test predictions are durably saved before the first test
native outcome. Every fixed request is probed regardless of predicted label;
predictions cannot censor difficult outcomes. Labels mean native selection of walk plus physical validity;
they do not measure route completion, smoothness, pain relief or consciousness.
Missing-class recalls and balanced accuracy are null. Brier uses raw relative
two-completion scores; adjusting the parent's decision cutoff does not calibrate
its probabilities. No hyperparameter search, automatic retry or model swap.

Promotion eligibility requires zero false admissions, both recalls at least
0.95, and strictly higher test accuracy than both the calibrated parent and
the frozen enriched comparator. Even an eligible result does not enable the
existing API advisor. The current integration accepts its older schema; this
experiment intentionally does not silently substitute an incompatible bundle.

## Reproduce

Use the existing pinned v0.1 dependencies and source-pinned local base model.
No OpenAI key or live model request is needed.

```sh
.weight-env/bin/python -m unittest examples.nasuraya_language_body.test_body_language -v
.weight-env/bin/python -m examples.nasuraya_language_body.experiment prepare \
  --output /private/NEW-body-language-run --previous /private/verified-transfer-v03
.weight-env/bin/python -m examples.nasuraya_language_body.experiment train \
  --output /private/NEW-body-language-run --base /private/pinned-smollm-base
.weight-env/bin/python -m examples.nasuraya_language_body.experiment verify \
  --output /private/NEW-body-language-run --base /private/pinned-smollm-base
```

Preparation copies both ancestor adapters and their ancestry. After that the
run is independent of the v0.3 runtime directory. The base remains a separate,
hash-verified dependency. A separate process forbids network, validates all 88
native receipts, recomputes metrics and promotion, and reloads all three adapter
states to reproduce four model/input combinations without training or body
cycles. `run-started.json` prevents silently retrying a partial training run.
Public evidence contains reduced rows and predictions; full synthetic plans,
receipt SQLite and actual adapter binaries remain in the private checkpoint.
