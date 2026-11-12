# Tadash artificial interoception v0.1: prospective protocol

Frozen before implementation and first test execution. Research software only.

## Scope and hypothesis

Palm touch is exteroceptive input; this experiment tests its **internal-state
consequences and functional self-monitoring**, not visceral physiology or
subjective consciousness. Numeric afferents must change persistent state,
attention, episodic trace and bounded decisions without a text instruction.
Native 195 kg body physiology, visual 78 kg target and 78 kg mechanics remain
distinct. No production deployment, external service, model API or credentials.

## Pinned audit and reuse

Base: PR194 `6fa94d012cd5265dc407e946ef47dbe7d700a367`, stacked on PR193/192/176.
Main: `a532f24a5b3eb7a31df6d200950c7287e1e96a35`.
PR177: `bef3f9bb42f2365688e3bee3fc5e158881f40510`.
PR182: `d78e5272300c28729c54c4a61a52593f297b055d`.
PR185: `140e6a2c82755dd5163200106ded9ebc2b484660`.
PR192 audited head: `b2b49ec06de47d662b27bc6b65c7e66ec7289ef4`.
Baseline: existing DIOS suite 177 tests passed locally before changes.

Reuse CognitiveSession / EvidenceLedger, AdvisoryGoalPlanner / GoalMemory,
critical_review, DecisionCore and PR185's exact Rolyel module. Reuse the native
source manifest and BodyLoop; preserve source-pinned runtime files unchanged.
The existing sensory legacy bridge uses direct region/contact labels and fixed
symbolic mappings. Existing interoceptive trends detects HR/RR mean shifts.
Neither supplies blinded palm modality/intensity decoding; neither is replaced.

## Design frozen before outcomes

- Six synthetic afferents: two palms, three mixed receptor channels each.
  Mechanical, thermal and vibration inputs; none; held-out compound novelty.
  Variable intensity/duration/frequency/noise and monotonic simulation time.
- Stateful numeric filtering, adaptive spatial attention, bounded 12-frame
  memory, prediction residual and load. Decoder accepts only numeric internal
  features, never Stimulus, condition, seed, trial ID, label or truth.
- Learned nearest-neighbour decoder (k=9) for detection, region, modality and
  intensity; confidence from smoothed votes. It is a small supervised model.
- Train: seeds 710000–710279 (280 independent episodes, no novel modality).
  Diagnosis: 720000–720139 (140). Acceptance validation: 730000–730139 (140).
  Locked test: 740000–740499 (500). Development unit fixtures use seeds <10000.
- Train has clean/no-stimulus/misleading conditions; later sets have five
  balanced conditions: real, none, misleading label, noisy, novel compound.
  Novel data is never used to train any decoder. Label is randomized independently
  of the sensor-generation noise; misleading metadata cannot change afferents.
- Prediction record is committed to a flush-on-write JSONL observer before
  truth is revealed. Separate evaluator owns truth. This is a logical API
  boundary, not a sandbox against malicious in-process code.
- Run1: train baseline, diagnose errors. Run2: add only non-novel diagnosis
  episodes to candidate training and choose confidence temperature on diagnosis;
  accept on separate validation only if binary Brier improves and detection
  accuracy decreases by no more than 0.02. Otherwise retain baseline. Run3:
  compare frozen selected and baseline models on untouched test. Record both.
  DIOS monitors every phase; candidates, rejection and rollback remain recorded.
- Compare random predictor, visible-label classifier, internal state without
  correction, full system; also truth oracle (explicitly privileged reference).
  Run memory-off, attention-off, correction-off ablations with separately fitted
  models and the same seeds. Novelty scores are exploratory, no success claim.
- Report accuracy, FPR, FNR, location/type accuracy over all true stimulated
  examples (misses count wrong), intensity MAE, binary Brier and 10-bin ECE,
  checkpoint/memory consistency, changed action rate, milliseconds/episode and
  traced peak allocation. Also report all five conditions separately.
- Paired bootstrap (2,000 draws, seed 748001) for full-minus-baseline detection
  accuracy and Brier; descriptive only. No holdout-driven retuning.

## Engineering acceptance

Input bounds, finite values, unknown keys, monotonic time, no-label readout,
predict-before-reveal, split separation, deterministic replay, cold continuation,
corruption detection, stop/budget preservation and regression tests. A digest is
not authentication. Offline runtime must actually execute bounded actions;
native body test must report requested and returned action plus checkpoint.
Scientific success is not required for engineering delivery; retain failures.

## Next independent experiment

Use authenticated native sensor outputs, a separately authored environment and
equal-information temporal baselines. Test persistence, remapping, habituation,
and action utility rather than interpreting introspection text as experience.
