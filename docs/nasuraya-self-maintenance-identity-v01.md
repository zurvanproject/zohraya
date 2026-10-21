# Nasuraya Self-Maintenance & Identity Continuity v0.1

**Scope:** additive, bounded, offline-only integration on the *synthetic* source-pinned Tadash runtime. No physical sensors, actuators, model weight updates, subjective experience claims, or live API calls. Native `UnifiedBody`, `DecisionCore`, `ReflectionCycle` and recovery provenance are unchanged.

## Audited sources, 13 October 2026

Base branch: `nasuraya/agent-loop-v03` at `601653d9acc302563e98b0a8f4fa9e6ed15011d5`, PR #1 still open. Verified file interfaces: `runtimes/tadash_body/unified_body_v2.py`, `persistent_embodiment_v1.py`, `decision_core.py`, `reflection_cycle.py`, `runtimes/tadash_body/DECISION_CORE.md`, `examples/nasuraya_body_loop/host.py`, `worker.py`, `api_host.py`, the saved recovery docs and the existing body-loop tests. The motion mirror, world model, self-initiator and fictional organ descriptions are *not* presumed to be one integrated autonomous cognition.

## Addition

- `self_maintenance.plan()` observes native checkpoint SHA and explicit synthetic minimum-state indices. Energy, fatigue, pain, sleep pressure, balance (unitless 0..1) and synthetic temperature (°C fixture) determine a deterministic bounded preference of `walk` versus `observe`. `compute_load_proxy` and `integrity_proxy` are declared engineering indicators, **not independent biological measurements**.
- A recorded motion veto on a previous `walk` adds a recalled reason and changes the next preference to `observe`. The existing native decision core may still rank a different eligible action, and the native body keeps its safety veto and conservation audits.
- `IdentityContinuity` persists a versioned set of *computational* principles and scalar beliefs in the **same locked session SQLite database**. Belief revision requires bounded reason and provenance; immutable constitutional rules cannot be revised via that interface. Reverting is another appended version; no destructive rewrite of identity history.
- `SelfMaintenance` persists goal target (1..3), per-cycle intent and decision ID **before** the body call. The next launch inspects the authoritative native ledger. Confirmed completed calls are reconciled without re-execution; unknown or running calls block. A completed result is cross-checked against the native receipt to detect accidental inconsistency.
- The supervisor runs for at most 3 cycles per goal and respects the existing global native action budget. It requires explicit CLI invocation; no daemon, external scheduler, sandbox escape, paid API, shell tools, or self-modifying model.
- SHA-256 detects accidental changes to the identity history but is not an authenticated anti-tamper signature against a privileged database editor.

## Reproduction on the full repository (Linux, Python 3.12)

Use a **new** synthetic session; do not run this on a user's historical database:

```bash
python3 -m examples.nasuraya_body_loop test
python3 -m examples.nasuraya_body_loop start --session /tmp/nasu-sm01.sqlite --fixture sleep --max-actions 3
python3 -m examples.nasuraya_body_loop maintain --session /tmp/nasu-sm01.sqlite --goal-id smoke-v01 --target-cycles 2
# Process restarts; an identical goal is not repeated
python3 -m examples.nasuraya_body_loop maintain --session /tmp/nasu-sm01.sqlite --goal-id smoke-v01 --target-cycles 2
```

An isolated ten-test unit suite can also be run without the recovered native runtime:

```bash
python3 -m unittest examples.nasuraya_body_loop.test_self_maintenance -v
```

GitHub Actions `Nasuraya recovered body loop` repeats the native regression tests, unit tests and the two-invocation synthetic CLI smoke test. Confirm actual workflow results before claiming end-to-end integration.

## Failure modes and known omissions

No automatic re-execution of uncertain effects. Changes to goals on reopen are rejected. The native loop may veto preferences. No separate intelligence learns a generalizable model; memory influence here is a deterministic one-step feedback rule. No autonomous belief proposals, calibrated risk model, real temperature/energy instrumentation, long-running service, agent-led goal creation, or external safety attestation. A destroyed/overwritten session database cannot be recreated from an identity hash chain.

**Next priority:** validate one frozen benchmark where native body state and verified history jointly change the selected action under a cold process restart, and compare baseline versus this supervisor; use no paid API.
