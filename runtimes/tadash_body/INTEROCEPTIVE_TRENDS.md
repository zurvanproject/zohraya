# Native heart-rate and respiratory-rate trend observations

`InteroceptiveBody` wraps an existing `NeuroPelvicBody` and adds a streaming
observation to each completed one-second simulator cycle. It uses the actual
`after_body.HR` and `after_body.RR` outputs. Each channel reports its current
value, running-mean reference, warm-up status, Page-Hinkley scores and the
direction of a detected mean shift. The selected native action and sidecar
phase accompany the observation so an intentional breathing change can be
interpreted in its context.

## Source and scope

The detector is adapted from [River](https://github.com/online-ml/river) commit
`8d1cfcf1bcb901d8b6c94e4a1454e984eee0642c`. The PageHinkley source has only an
attribution comment and changed imports; a small local dependency surface
implements the required running mean and detector flag. The complete River
package is not installed. The original sources, BSD-3-Clause license and
provenance are retained under `third_party/river/`. The observed latest release
was 0.26.1, published 21 August 2026; the inspected main commit was dated
30 October 2026. Page-Hinkley is an established method, newly adopted here.

The observer does not select actions. Existing body receipts, gas/resource
accounting, neuro-pelvic policy and checkpoints are preserved under the wrapper.
The model is the reduced native 195 kg solver inherited from PR #98, not the
separate 78 kg articulated model. These are simulator variables, not ECG or
respiratory-belt recordings. No heart-rate variability is derived from them.

## API

```python
from interoceptive_trends import InteroceptiveBody

observed = InteroceptiveBody(existing_neuropelvic_bridge)
receipt = observed.cycle(
    event_id="unique-observed-cycle",
    at_utc=next_utc_timestamp,
    duration_s=1.0,
    expected_revision=observed.bridge.revision,
)
print(receipt["interoception"]["channels"])
saved = observed.checkpoint()
resumed = InteroceptiveBody.restore(saved)
```

Use a distinct event ID for each newly executed body cycle. A matching replay
returns the cached observation without advancing the detector or body.
Checkpoints retain the running means, cumulative scores, phase clocks,
native state, source fingerprints and sixteen recent receipts. A request
older than that cache fails rather than executing again. Sorting JSON keys
does not reorder chronological receipt eviction after restoration.

Only one-second cycles are supported; a gap, duplicate observation or different
cadence is rejected before execution. Attach to an existing bridge to begin a
new observation history; historical receipts are not backfilled. The first
19 samples after attachment or a detector reset are labelled `warming_up`.

## Fixed development protocol

The protocol file was written before its first evaluation. The detector uses
`min_instances=20`, `delta=0.01`, `threshold=5`, `alpha=0.9999`, both directions.
HR is divided by 10/min and RR by 3/min before detection. These are authored
scales and thresholds, not clinical thresholds or learned physiological units.

```sh
python3 synthetic_fixture.py
python3 -m unittest -v test_interoceptive_trends test_neuropelvic test_neuropelvic_body
python3 run_interoceptive_trends.py --output /tmp/tadash-trends-fresh
python3 run_tests.py --output /tmp/tadash-native-fresh
```

Run the unit-test commands in a fresh checkout: `synthetic_fixture.py` writes
generated default files. Use an empty evaluation output directory. The evaluator creates an isolated
copy with generated defaults, checks 96 signal streams, executes matched
coupled/ablated native trajectories with and without the observer, and verifies
continuation in a separate Python process. Results and the full protocol are
retained in `evidence/interoceptive_trends/`.

## Interpretation

A detected change is a shift of the running mean. It may arise from an intended
action or natural settling of this solver. It does not establish danger,
unexpectedness, successful recovery, disease or subjective sensation. The
detector can report another change as a trajectory continues and resets its
reference on the following sample. It is not a calibrated probability model.

The finite, authored development fixtures are not a blinded generalization
study. Native traces must be read alongside action context and the documented
parameters. The new wrapper remains opt-in and no background service is started.
