# Nasuraya Proprioception: bounded review baseline 0.1

هدف این بخش، تصحیح یک نمونهٔ پیشنهادی Gemini و ساخت **هستهٔ حس عمقیِ مشاهده‌گر و محدود** است. این کد یک سامانهٔ کنترل حرکتی اجراپذیر، فیلتر کالمن، ربات خودمختار، موتور فیزیک سه‌بعدی یا حس واقعی نیست. به وضعیت اصلی Tadash یا کدهای PRهای باز دست نمی‌زند.

## Provenance

- Body phenotype 170 cm / 78 kg: **provisional fictional engineering profile**.
- Original draft declared 114 degrees of freedom but the 18 joint entries sum to **111**; neither value proves an articulated rig.
- PR #68 is **open and unmerged**. Its saved `zohraya/self_model.py` is a read-only audit projection with `get_telemetry`, *not* a mutable `update_interoception` service.
- The geometry and 3D motion in this review module are deliberately limited to a **world-frame 2D three-toe support hull**.
- `EUI` is a bounded heuristic, never a calibrated probability of falling or proof of biological safety.
- Synthetic model identification uses a 3-feature linear toy oracle. The holdout set is distinct from training **within the same artificial function**. It cannot establish physical generalization.

## Why the supplied Gemini generator must not be merged

1. In its top-level builder, `Any` and `Tuple` type names lack imports, so direct execution raises `NameError` before writing the package.
2. The claimed Kalman estimator is not a Kalman update and publishes no meaningful covariance.
3. The original support polygon is a **rectangle bounding toe positions**, not a convex hull. The perimeter is wrong for single-foot support.
4. Unknown joints are passed through unchanged; nonfinite values can slip through the torque/angle clamp.
5. In the original adaptive learner, tail and ankle gains explicitly drift toward `1.0`, an oracle target. That is not learning identified from observation.
6. In the bridge, estimated energy debit is computed from torque magnitude without angular displacement (unit inconsistency), and its `update_interoception` contract conflicts with the read-only PR #68.
7. The ten scenarios are mostly **independent, single synthetic steps**, not ten validated walking or balance trajectories. "Ground-truth physics" is a separate toy equation, not a rigid-body solver.
8. The HTML demonstration is **2D Canvas**, not a 3D body rig.
9. The "50 unseen perturbations" writeup does not match the code, which constructs **25** synthetic held-out inputs.
10. No physical fall probabilities or safety assurances are supported.

## Implementation

`engine.py`: validate explicitly synthetic packets, finite units, source flags,
toe contact geometry, friction and known joints. Compute a **convex** hull from
only contacting toes; compute signed horizontal XCoM margin only for a vertical
gravity vector. Stale inputs, no support, tilted gravity and friction violations
all deny motion. A `STEP` intent is denied because there is **no authorized
actuator**. Even an "OBSERVE_ONLY" result is only read-only advice.

`benchmark.py`: normalized LMS on a synthetic linear model; distinct
deterministic training and holdout examples; no oracle parameter is read by
the learner. The resulting RMSE must be calculated from real execution logs,
never prefilled claims. No API, external package, money or physical actuation.

### Local verification

At repository root:

```bash
python3 -m unittest discover -s examples/nasuraya_proprioception/tests -v
python3 -m examples.nasuraya_proprioception.benchmark --output /tmp/zohraya-proprioception-benchmark.json
```

GitHub CI checks the unit tests and uploads the generated benchmark receipt.
No main-branch merge is implied. Feature dependencies on PR #68, PR #58,
and older `runtimes/tadash_body/` remain **not integrated**.

## Next honest milestone

Replay actual stamped motor and body receipts from the pinned Tadash simulation;
add provenance checks, time-domain state estimation with uncertainty covariance,
orientation-aware foot contacts and actual forward rigid-body dynamics. Compare
a controller with and without the model on held-out disturbances. Only then
consider integration behind an explicit feature flag and the native controller veto.
