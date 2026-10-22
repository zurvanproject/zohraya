# Nasuraya tissue observer v1

This lab adds six regional diagnostic beds to the fictional body design:
brain, myocardium, left/right Resonan, Spandar capsule and facial tissue.
It consumes copied observables from a hash-verified native checkpoint.
It does not modify the body, authorize actions, debit energy, train a model,
solve cellular biology or repair a wound. All new coefficients and tissue
time constants are authored, uncalibrated scenario assumptions.

## Run

Python standard library only:

```
python -m unittest discover -s examples/nasuraya_tissue_lab -v
python examples/nasuraya_tissue_lab/run_lab.py --database /path/to/session.sqlite --output /path/to/evidence
```

Read-only SQLite access observes the existing `nasuraya-body-loop` runtime.
Use a coherent SQLite backup for an archived session, including committed WAL
transactions. This tool does not open a body host or advance native time.

## Contract

Regional blood flows are fixed fractions of the supplied total times local
patency. The complement is explicitly unassigned to this six-bed observer;
blocked flow also stays unassigned, without simulated redistribution.
There is no resistance network or cardiac pressure/volume solution.

Delivery is a dimensionless index:

```
delivery = min(1, regional_Q/(reference_Q*share)) * oxygen_proxy / (1 + 2*edema)
```

`reference_Q` must be explicit. The runner uses the recorded snapshot's own
flow for normalization; that does not validate it as physiological normal CO.
The recorded October 14 fixture has Q=49.5 L/min, whereas the design atlas
uses a separate illustrative 10.5 L/min target. Oxygen adequacy is a native
proxy, never treated as arterial saturation or oxygen content.

Inflammation and edema relax toward authored targets (120 s and 60 s).
They are indices, not ml of water, cytokine concentrations or cell counts.
Face/brain partition the already paid neural budget (30%/70%), and
Resonan L/R/Spandar partition special (30%/30%/40%). Immune grant is
partitioned among the six beds by their declared flow weights. These are
annotations of existing paid energy; no extra energy is spent. Myocardial
metabolism is outside this annotation budget; it is never called free work.

The output `function_ceiling` responds to perfusion, oxygen proxy, edema,
inflammation and the special/neural paid fraction. It is a diagnostic
capacity ceiling only; it is not connected to native actuation. In
particular no immune-antigen or tolerance solver is present.

Every advance consumes a unique source ID. Recorded tick order must increase;
constant-input forecasts use explicit `forecast` labels and separate observer
time. JSON checkpoints carry schema, source history and SHA-256 integrity;
this detects accidental corruption, not hostile tampering.

## Verification

12 tests cover shared flow/paid budgets, zero oxygen, budget withdrawal,
unilateral obstruction, lymphatic failure with inflammation, cold restart,
replay/stale rejection, invalid-input atomicity, immutable inputs, state
validation, flow loss and forecast/time limits. The read-only runner separately
checks the source database byte hash and checkpoint integrity. Six 180-second
counterfactual traces are predictions under constant inputs, not new body
experience. Native source files and session continuation are unchanged.

Design basis: standing anatomy v06 (2026-10-02), Spandar v02 (2026-10-02),
whole-body audit (2026-10-11), and body-loop PR #7 at
49fd31c0f46ce51231203b198bb2433ed35133d7. Anatomy/physiology/histology atlas
dated 2026-10-14 separately labels inherited canon and new authored proposals.
