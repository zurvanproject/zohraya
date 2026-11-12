# Staged integration: one bounded, restartable local session

Authorized scope: integrate the available Nasuraya / Tadash / DIOS components.
Starting revision: PR195 `61050eb1a3079e9a0b422380d99a31cafc34915a`, incorporating
PR194's pinned cognitive/body/state/evidence adapters. New isolated branch;
no main merge, production deployment or remote messaging.

## Stage 1 — capability inventory and contracts

Record what executes, what is coupled per event, what is a frozen reference and
what has no live connection. Preserve native195kg/target78kg distinctions.
Reuse source-pinned body, neural/affect/genome fixtures, DIOS evidence, goals,
recovery, sensory state/decoder, Rolyel and local tool host. Do not reinterpret
frozen server/Moltbook/ritual records as current live state.

## Stage 2 — common event loop

One session ID, ordered event IDs, explicit sensory window, stable decoder,
attention/memory, workload observation, DIOS review, persistent goal, Rolyel
route and bounded action receipt. Supply simulation results back into next-step
state. No stimulus truth enters the inverse decoder. Existing text-only or
read-only capabilities must be labelled accurately in the same status report.

## Stage 3 — continuity and recovery

Durable SQLite event/checkpoint ledger with digests and compare-and-swap revision.
Exactly one committed simulated state transition per unique event ID; conflicting
replay rejected. Existing goal/evidence stores are projections: keep an operation
intent and reconcile deterministic idempotent projections before the next event.
Abort/retry semantics must distinguish local pure simulation from external side
effects. No exactly-once physical or remote execution claim. Stop persists,
budgets cannot reset on reopen, stale exports cannot permit motion.

## Stage 4 — end-to-end validation and delivery

Test uninterrupted versus fresh-process continuation, duplicate/conflicting IDs,
interrupted projection recovery, checksums, source/model pin mismatch, stop,
budgets, workload pause and native protective veto. Run portable and Linux native
scenarios, existing relevant regressions and a single inspectable demonstration.
Retain the actual results and any failures. This is an integration contract test,
not a new held-out interoception benchmark or consciousness experiment.

Deliver one CLI/API and report with component availability, current state,
uncertainty, action, outcome and next unmet connection. Components that remain
unconnected must not be silently reported as integrated. Paid LLM/image APIs and
authenticated live server ingress are not part of this offline session.
