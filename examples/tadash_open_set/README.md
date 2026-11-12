# Tadash Open-Set Research v0.1 (not deployed)

This is an isolated experimental open-set abstention wrapper for the
unchanged PR #195 numerical decoder. The branch is stacked on PR #196 but
is NOT wired into PR #196 Session, action routing or native execution.

It produces one of three outcomes: no stimulus, familiar stimulus with a
named type, or abstention/unknown. Unknown means that the positive occurrence
does not conform sufficiently to the familiar classes; it does not name a
new modality. Its conformal p-value is NOT a calibrated posterior probability
of novelty.

## Frozen research protocol

* Original 392-example PR195 full decoder, reconstructed using train seeds
  710000..710279 plus non-compound diagnosis 720000..720139, temperature 0.5.
  Verified fingerprint:
  3afd0c642a07759bcb637ab0d470b3c358c9e7109d811ce887ba4f65cb37c993.
* Calibration: 810000..810799, 640 KNOWN rows after excluding novel cases
  BEFORE constructing them (including 160 no-stimulus episodes).
* Known-only validation: 820000..820499, 400 rows.
* Locked final: 850000..850699: 300 known, 100 compound unknown, 100
  independently authored pulsed unknown, 100 quiet absent and 100
  high-noise absent.
* Fixed class-conditional nearest-three shape-distance anomaly score,
  alpha = 0.10, with no final-test tuning. The score references the frozen
  decoder's existing examples. It is not trained on any novel family.
* All time samples of one episode stay in the same split. Test set is
  synthetic and NOT externally independent or publicly preregistered.

Python 3.11+; standard library. From the repository root:

~~~sh
python -m unittest examples.tadash_open_set.test_open_set -v
python -m examples.tadash_open_set.experiment calibrate --output /tmp/tadash-open-fit
python -m examples.tadash_open_set.experiment evaluate \
  --calibration /tmp/tadash-open-fit/calibration.json \
  --output /tmp/tadash-open-test
~~~

Use fresh directories. Calibration and heldout output include immutable
fingerprints, metrics, per-episode predictions and hash-chained ordered
events with each prediction logged before truth reveal. The CI workflow
runs Linux and Windows and retains synthetic-only artifacts.

## Honest limits

The heldout test abstains correctly on 196/200 unknown events but fails
to recognize 98/100 high-noise NO-STIM episodes as absent, and unnecessarily
abstains for 52/300 known events. The old occurrence decoder is unchanged.
Novelty and noise are partly confounded. This does NOT establish robust
three-way recognition and must not be deployed.

The type-specific toy action/cost comparison is counterfactual; PR #196
does not consume these labels for physical/remote execution. Source,
parameters, and code were not retuned after observing the locked test.

See docs/research/TADASH_OPEN_SET_ABSTENTION_RESULT_2026-11-12_FA.md.
