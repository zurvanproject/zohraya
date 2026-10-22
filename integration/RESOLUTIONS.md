# Unified capability integration, 2026-10-21

## 2026-10-22 refresh

The refresh incorporates main `5330cbee347c1ef5b7c3a77e74f91398d45aa76f`
and the read-only self-model source from PR #68 at `4433ba8`.
`sources.json` retains the original source inventory and records both new heads.

- Preserve the active daily `host.py`, its tests, `research_host.py`, and both
  research engines byte for byte from main. `verify_sources` enforces this
  because the live model memory is bound to the exact engine bytes.
- Keep the six-hour prototype as `cadence_host.py` with its own fixture and
  tests. The default reader does not request a nonexistent cadence ledger.
- Keep the daily schedule, maintenance job, dispatch modes, concurrency and
  permissions identical to main. Expand only verification in that workflow.
- Add `research-host` and `research-day` as explicit catalogue entries, while
  preserving the meaning of existing commands.
- Add `self-observe`: use the verified native audit and PR #68 projection on
  the existing checkpoint, in a separate credential-free process. SQLite is
  opened read-only with the native host's inode-lock and single-link rules;
  active writers and unresolved runs are rejected. Unknown integrity and
  stale evidence remain explicit.
- The shared demo now observes the same post-action checkpoint and proves
  that observation and cold replay add no body cycles.

Current scoped results and reproducible commands are in
`refresh-v02/summary.json` and `../docs/nasuraya-unified-v02-fa.md`.
The test counts below remain the historical 2026-10-21 baseline.

The integration starts from main `884ae8a778bbe1d60fcf6e7b6d5263ed5945833a`.
`sources.json` records all 59 open PR heads and two additional source branches.
Their latest commits are retained in ancestry; no PR head was overwritten.
The mutable absence/host ledger stays on its existing branch.

## Resolved interfaces

- Body command registration is the union of maintenance/adaptive commands,
  wakeup/care/experience/recovery commands, metacognitive admission and the
  language advisor. Existing required arguments and explicit activation remain.
- Recovery uses the newer four-call observe/evaluate/action/evaluate contract,
  with distinct call IDs and decision-context admission. The older three-call
  implementation is superseded.
- API body actions retain durable intent-before-execution, canonical duration
  for metacognition and the post-observation admission tool. Evaluation retains
  its next-decision context. No action/call budget is replenished by integration.
- The native BodyLoop retains sleep/rest, metacognitive reconciliation and the
  bounded social-event input. Replay identity includes the external event.
  Metacognition schema v2 now validates and carries that same input through
  prediction context, durable intent and native execution. Unseen social walk
  contexts remain deferred in enforcement mode. Aesthetic observation and sleep
  both execute under native arbitration with receipt-bound learning; their
  joint tests include reopened-ledger replay. Old source-bound v1 sessions are
  not silently migrated.
- Research keeps the dependency-light native snapshot and the stronger finally
  check for observer mutation, while retaining the optional PredVLA study.
  The combined lock uses all nine unchanged upstream blobs and preserves the
  supplemental BSD notice check. No upstream code or historical receipt is edited.
- Star motion CI retains recovery tests and adds the spiral branch tests.
- Aggregate physiology, the original articulated fixture, the 85 kg articulated
  walker and spring-mass running remain explicit models. Their checkpoint formats
  and physical scales are not interchangeable. The genome's legacy structural
  proposal stays bound to its original fixture; it is not silently rescaled.

## Shared operation

`python -m nasuraya catalog` is the dependency-free inventory.
`python -m nasuraya <capability> ...` delegates to the existing guarded entry point
in a separate process. It supplies no hidden arguments, grants or sessions.
Optional interpreters can be selected by absolute `NASURAYA_PYTHON_MECHANICS`,
`NASURAYA_PYTHON_TENSOR` and `NASURAYA_PYTHON_SDK` paths. Source checkout use is
required; the existing Continuity Kit wheel remains its own smaller product.

`python -m nasuraya demo --output NEW_DIRECTORY` runs a synthetic aggregate-body
session: verified genome baseline + identity policy, message appraisal, decision,
native body action, persistent feedback, and exact status after cold replay.
The genome is retained as a verified proposal sidecar and does not control body
parameters. This is one demonstrated cross-component route, not a claim that
all research experiments participate in every action.

The test runner isolates each module to avoid legacy native import and fixture
state crossing between suites. Optional dependencies and skips are reported.
Native runtime tests retain their original separate harness. Existing source-bound
private/live checkpoints are not migrated; a source mismatch still stops execution.

Local verification records 926 passing component tests plus 99 passing native
tests. Another 26 historical-fixture tests were skipped and the seven-test
coordinated-support suite was blocked by its missing private checkpoint. These
33 cases are not counted as passes; running every suite without those fixtures
still returns a failure. Synthetic policy/recovery tests remain active. See
`verification.json` for final per-module results and initial environment failures,
and `test-environment.json` for actual versions. The full optional upstream
training/UI dependency stack has not been validated.

## Deployment boundary

The six-hour implementation from PR #43 remains an isolated prototype and is
not selected by the active workflow or the shared catalogue. This refresh
retains the existing daily production contract, with no ledger migration.
Publishing the integration branch runs verification; it does not deploy the
shared body or change the live control branch. Any later cadence migration
requires its own review and explicit activation.
