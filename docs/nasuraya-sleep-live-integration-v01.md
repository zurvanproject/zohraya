# Bounded sleep on the live-agent lineage

## Problem and source heads

PR #14 (`4db2caee1c4fd87d85c6c3c71a1179adc4cb0b7d`) retained only
`walk`/`observe` in its API tool and host next-decision rule. PR #7
(`49fd31c0f46ce51231203b198bb2433ed35133d7`), based on PR #6, added
`sleep`/`rest`, a local recovery controller and a return-to-motion goal.
This draft is based on PR #14 and transplants the PR #7 commit; it does not
merge either draft or rewrite the main checkpoint.

## Contract reconciliation

| Shared component | Previous divergence | Integrated behavior |
| --- | --- | --- |
| `api_host.py` | Only walk/observe in #14 | One `BODY_ACTIONS` vocabulary for schema and validation; fresh SHA, run/session/turn binding and persistent receipts retained |
| `host.py` | Only two core candidates | Four candidates; decision core and native guards retain final authority; durations stay 0.1–1.0 seconds |
| `decision_context.py` | High pressure/fatigue suggested observe | Same validated threshold proposal as local recovery: sleep >0.65, otherwise rest if fatigue >0.45, otherwise walk |
| `experience.py` | Sleep/rest records rejected | Committed, verified sleep/rest records accepted in the existing reduced packet, with source hashes; no raw memory export |
| `recovery.py` | Local controller independent of transport context | Stops on blocked/unknown transport; preflights four remaining calls and observes/evaluates before one action, then evaluates |
| `scheduler.py` | Synthetic/API/care backends | Adds explicit host-only recovery backend; one bounded action per tick, same grant/window/attempt caps and inode lock |
| CLI/worker/CI | Independent commands | New vocabulary, recovery backend and integration test command; all older commands retained |
| README | Both branches appended at same location | Both scheduling/memory and recovery instructions retained |

The persisted `nasuraya-agent-run/1` goal and grants are unchanged. Tool call
identities, payload fingerprints, pending effects, transport recovery and orphan
creation review use the existing #14 paths. Recovery is simulated body work,
not elapsed-time healing: reopening or waiting never lowers sleep pressure.
The original care-policy version 1 and historical ablation are deliberately
retained to validate old care episodes exactly. Select a **new** explicit
`recovery` wake contract to use recovery; an existing `care` or `synthetic`
schedule is not silently reinterpreted.

## Safety and memory boundaries

- `observe` mode does not expose a mutation tool. The model cannot authorize
  grants, schedule wakeups, extend deadlines, reset counters or bypass locks.
- Native source and frozen fixtures are unchanged. `recovery-ready` is a new,
  explicitly synthetic near-threshold fixture, never a modification of a saved
  session. Its initial sleep pressure is 0.6501.
- Ready-motion feedback is scoped to fresh readiness after committed sleep/rest;
  old sleepy feedback remains stored and available in its original context.
  Native body vetoes still execute after core selection.
- A committed action whose result receipt was interrupted is reconciled from
  its stored decision. An effect with unknown outcome blocks further work.
- A saved **cycle goal** being complete does not prove **recovery** complete.
  A high-pressure fixture can spend its entire grant on sleep and still require
  a later, separately authorized continuation.
- Existing live remote sessions retain the tool definitions sent at creation.
  This patch does not claim to modify their tools in place. Fresh remote session
  creation must follow the existing transport and host-reconciliation rules.

## Reproduction

No API key is needed for these commands; the public CLI verifies all pinned
native source hashes and copies the runtime to an isolated directory.

```sh
python3 -m examples.nasuraya_body_loop api-test
python3 -m examples.nasuraya_body_loop sleep-integration-test
python3 -m examples.nasuraya_body_loop wake-test
python3 -m examples.nasuraya_body_loop decision-test
python3 -m examples.nasuraya_body_loop experience-test
python3 -m examples.nasuraya_body_loop care-test
python3 -m examples.nasuraya_body_loop creation-test
```

A recovery wakeup requires an already completed prior mission, exhausted body
budget and a host-issued continuation grant, just like the other backends.
The host registers that grant with `schedule --wake-backend recovery`, then
uses `wake` or the finite `wake-watch` command. Recovery does not install a
service or create a permanent scheduler. The new tests execute real SIGKILL
and fresh Python processes on disposable SQLite sessions with synthetic data.
API reconnection uses a controlled fake service, not `gpt-6-astra`.

## Verification status

See `docs/evidence/sleep-live-integration-v01/validation.json` for the measured
local results and commands. Live model selection of sleep/rest, live remote
reconnection across sleep, and recovery of the user's high-pressure checkpoint
remain untested by this change. No model request or original checkpoint update
is part of this integration.

Final local validation: **215 distinct tests passed, zero skips**. This includes
12 new integration tests, 65 API/continuation/native-recovery tests (including
SDK mock HTTP checks), 24 scheduler tests, eight saved-intent tests, 46
body/memory/care/creation-review/deployment regressions and 60 agent tests.
All 70 pinned native file hashes verified; the native runtime and frozen
fixtures have no diff from the PR #14 base.

The separate declared near-threshold demo executed `sleep → cold restart → walk`:
sleep pressure went from 0.650100 to 0.649441 at the end of the two cycles,
and terminal reread performed zero actions. This fixture result does not prove
full recovery from the main checkpoint's much higher pressure. All model and
external API requests in this verification were zero.
