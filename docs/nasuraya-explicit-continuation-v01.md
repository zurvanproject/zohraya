# Explicit continuation of a completed body mission

Previously an exhausted body/API budget could not accept a new mission while
retaining the body checkpoint and feedback. The live follow-up used a separate
runner with a one-time audited action-cap increase. The native bridge now has an
explicit host-only authorization operation. It keeps the original config,
consumption counters, prior goals, decisions and feedback; an append-only grant
adds 1–3 actions and 4–20 tool calls for one named new mission.

## Authorization contract

`authorize-continuation` requires the exhausted bounded session, an exact current
checkpoint SHA, a new grant ID, a new run ID and explicit action/call counts.
All earlier goals must be complete and all saved remote sessions deleted.
Failed body cycles, pending calls and unresolved effects block authorization.
An identical authorization retry returns the saved grant even after consumption;
changed parameters or another grant for the same run are rejected. New bounded
missions after a grant must have their own grant and match its action count.

The base body/API limits never change. Action limits include the granted additions
while all earlier action reservations remain consumed. Each granted run has a
separate tool-call allowance capped by its unchanged saved `max_calls` contract;
legacy calls continue to share the original cap and cannot consume a granted
run's allowance. Invalid calls spend tool allowance but do not spend an action
unless an actual decision reserves it. Lifetime limits are 100 actions and 100
tool calls across the base budget and grants. Reaching these limits needs an
explicit future design decision rather than automatic replenishment.

The grant operation is a trusted local CLI/application-host operation. It is
absent from the model's tool definitions. SQLite persistence and the existing
exclusive session lock serialize grants and body execution. This does not
authenticate arbitrary OS-level database edits or provide a remote scheduler.

## Commands

Inspect the current session and retain its reported checkpoint SHA:

```sh
python -m examples.nasuraya_body_loop status --session /private/session.sqlite
```

Authorize exactly one new body cycle and six tool calls:

```sh
python -m examples.nasuraya_body_loop authorize-continuation \
  --session /private/session.sqlite --grant-id followup-002 --run-id mission-002 \
  --observed-checkpoint-sha256 CURRENT_SHA \
  --additional-actions 1 --additional-calls 6
```

Use the saved base API call limit for `--max-calls`; `20` below matches the live
fixture's existing contract. Its new mission receives only its six granted calls.

```sh
python -m examples.nasuraya_body_loop api \
  --session /private/session.sqlite --output-dir /private/mission-002 \
  --api-mode bounded --target-cycles 1 --run-id mission-002 \
  --max-calls 20 --model gpt-6-astra --timeout-seconds 120
```

The default model instructions now explicitly require 0.1–1.0 seconds in
0.1-second increments and select 1.0 seconds for the finite mission. The existing
tool validation still rejects longer requests before body execution; this
clarification follows a live rejected 10-second request and does not relax the
guard. Host/core/native-body outcomes must be inspected separately.

Run the same saved completed goal with a new output directory and the default
`resume` policy to read its terminal result without a new API request or action.
Do not use `fresh` to read a completed result. No operation here runs repeatedly
or authorizes the model to create future grants.

## Verification

`python -m examples.nasuraya_body_loop api-test` includes the continuation tests:
unchanged body/history/base config, idempotent consumed grants after restart,
conflicting grants, stale/invalid grants, unfinished goals, unknown calls, active
remote sessions, goal/grant binding, isolated tool budgets, inherited feedback,
10-second rejection without effect, receipt replay without a second effect,
multiple explicit grants, and terminal recovery in a new process with network
methods forbidden. Existing body and API-recovery regressions remain required.

Live checkpoints and credentials remain private and are not committed. An API
completion is a software-body execution result, not model-weight training or a
biological measurement. Exact billing is not inferred from tool counts.
