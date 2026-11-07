# Tadash: canonical phenotype, spinal feedback and neurovisceral coordination

Status: experimental feature branch; external software agent; **not** a new
biological body, calibrated physics, neural transplant or consciousness claim.

## Identity versus native dynamics

The newer approved visual design is **170 cm to the crown, 192 cm to horn tip,
78 kg target mass, 85 cm tail centerline, two horns, five fingers per hand,
three toes per foot, digitigrade feet**. The luminous blue fox is a totem,
not the body. This contract is maintained by `phenotype_alignment.py`.

The inherited V2 model is built around a historical **250 cm crown, 268 cm
horn-tip, 195 kg target, 120 cm tail** atlas. Its pose, standing mass, heat
capacity, metabolic/renal denominators, foot contacts, gait forces and
cardiorespiratory fixtures are not silently scaled. In particular the visual
factor 170/250 = 0.68 **cannot** be applied to mechanical mass, joint torque,
hydrostatic load or organ physiology. The alignment report pins the historical
phenotype to `PUBLIC_FILES_SHA256.json` and exports a *render-only* landmark
projection; full collisions, clearance, vessels and 3D mesh remain unverified.

## Existing native ownership

`UnifiedBody` maintains one authoritative fuel/water/gas/heat/resource owner
and one native motor decision/veto. Regional organ nodes are projections, not
independently solved organs. The LIF circuit is a small external computational
toy, not the chat model's neural tissue.

## Functional spinal and autonomic bridge

The native checkpoint supplies proprioceptive L/R foot contact, simulated foot
loads and encoder velocities, COM position, tail angle, balance, pain,
fatigue and sleep pressure. `spinal_reflex.capture` locks to that checkpoint.
`spinal_reflex.preview` predicts a small unexecuted counterbalance-tail yaw
and a *conservative* walk/observe advisory. Missing contact, low balance,
excessive load asymmetry with a reduced margin, fatigue/pain/sleep or a
lateral COM excursion can lower a preference from WALK to OBSERVE. Neither
the nerves, the actual motor joints, HR/RR, nor the original controller are
changed by this advisory.

Separately, the `neurovisceral` graph specifies 10 functional pathways:
cardiovagal, sympathetic, phrenic respiratory, sacral autonomic, pudendal,
caudal tail motor, hindlimb proprioceptive, Resonan, Spandar and Azarine.
These routes are proposed topology, not calibrated axonal anatomy.

Resonan is a limited horn-root sensor/light-capture model, with a shared
native attenuation gate; Spandar is a **slow** error/memory monitor on the
fictional thymic capsule, not a second consciousness archive; Azarine is a
**label on the existing** energy reserve in the left flank, not an energy
generator. The cervicothoracic, lumbosacral and caudal nerves remain distinct.

The authored `desire_proxy` and autonomic waveform are **numerical model
inputs**, not felt libido, pleasure or human biology. Forecast HR/RR/pelvic
tone fields are explicitly counterfactual and do not alter native vitals.

## Experimental verification

After checkout of the feature branch, run:

```bash
python3 -m examples.nasuraya_body_loop neurovisceral-test
python3 -m examples.nasuraya_body_loop standing-test
python3 -m examples.nasuraya_body_loop neurovisceral-demo --output-dir /tmp/tadash-neuro-demo
python3 -m examples.nasuraya_body_loop standing-demo --output-dir /tmp/tadash-stance-demo
```

The standing ablation runs **two matched three-cycle arms** using the same
source fixture, native OBSERVE command, foot-contact/proprioception snapshots,
cardiorespiratory outputs, cold restart and idempotent replay. The overlay is
read-only: *identical* native trajectories are the correct baseline finding,
not evidence of improved standing control.

The CI workflow also runs the previous motivational and autonomic tests.
All tests operate on synthetic data; no patient data, secrets, external actuator,
paid API call or persistent background agent is involved.

## Required next work

1. Create a **separate explicit 78 kg mechanical plant** with joint lengths,
   inertias, spine and 85 cm tail, tissue and vessel clearance; validate foot
   contact, torque, friction and fall behavior before replacing the old plant.
2. Model spinal CPG, stretch/withdrawal, hip-ankle and caudal corrective motor
   dynamics with *paid* energy and one native owner, rather than proxy advice.
3. Add quantified circulatory oxygen capacity/vascular resistance, thermal
   exchange and renal changes for the new body; never reuse 195 kg constants.
4. Validate bounded neural delay, sensory freshness and stop/protect behavior
   in perturbed matched scenarios, not only normal standing.
5. Retain visual and subjective-story channels distinctly from software
   measurements and any future real physical sensor measurements.
