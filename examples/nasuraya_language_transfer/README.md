# Frozen language transfer study v0.3

This study evaluates the previously frozen `choice_balanced` adapter against
its calibrated parent on 42 authored software-body states. It does not train,
recalibrate, change prompts, select a replacement advisor, or call a live API.
The native selected action and physical validity provide outcome labels.
These are controlled source-pinned software fixtures, not real-world samples.

`protocol.json` fixes five families: six controls, ten fatigue states, eight
left-region slow pain proxy states, twelve intermediate-friction states and
six combinations. Every state is cloned independently from a synthetic warmed
body. Direct initial fatigue/pain assignments are explicitly journaled.
The native sensory constructor supplies a consistent initial raw readout;
warmed filters, clocks and realized frame counts are retained, and the stale
last sensor frame is cleared. No new realized frame, accumulated exertion,
injury or healing is claimed. Earlier cognition receipts remain historical.
No user body or native equation is modified.

The original v0.1 prompt is intentionally unchanged. It exposes sleep pressure,
duration, zero/nonzero ground category and audit restriction words. Numeric
fatigue, numeric pain, pain location, and nonzero friction magnitude/asymmetry
are omitted. Exact text aliases are recorded before outcomes. Afterwards,
contradictory labels within an identical prompt group quantify an empirical
error floor for a deterministic predictor of that text. It is a bound for
this finite fixture set, not a universal physical or architectural limit.

## Run

Use the existing v0.1 pinned dependencies and local pinned SmolLM2-135M base.
The original v0.1 and v0.2 checkpoints are needed only during preparation;
the resulting run contains its own frozen copies of both adapters and their
ancestry. Full base weights remain a separate source-verified dependency.

```sh
.weight-env/bin/python -m unittest examples.nasuraya_language_transfer.test_transfer -v
.weight-env/bin/python -m examples.nasuraya_language_transfer.evaluate prepare \
  --output /private/NEW-transfer-run --primary /private/verified-v02 \
  --parent /private/verified-v01
.weight-env/bin/python -m examples.nasuraya_language_transfer.evaluate evaluate \
  --output /private/NEW-transfer-run --base /private/pinned-smollm-base
.weight-env/bin/python -m examples.nasuraya_language_transfer.evaluate verify \
  --output /private/NEW-transfer-run --base /private/pinned-smollm-base
```

Both model parameter hashes and effective LoRA matrices are verified.
`predictions-before-outcomes.json` is persisted before the first target walk;
all 42 native outcomes are recorded without updating the old self-model.
The parent threshold stays 0.3299630433320999; primary threshold stays 0.5.
Audit preflight, always-admit and always-defer are explicit comparators.
Metrics include per-family confusion and both class recalls. Missing-class
recalls and balanced accuracy are null. Two-choice Brier scores concern
relative label completion scores, not calibrated physical probabilities.

A separate process reloads both adapters, forbids network connections,
checks native receipt labels and reproduces predictions without body cycles,
optimizer steps or learning. Public reduced evidence and the Persian report
record findings; the private checkpoint retains full plans, receipts and
adapter binaries. A failed initial preparation (caught stale sensory readout)
is retained as a pre-label failure, followed by the declared fixture correction.
The evaluation cannot be automatically retried in a directory with labels.
