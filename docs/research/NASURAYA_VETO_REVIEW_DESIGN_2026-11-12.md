# Protective veto review — isolated experiment v0.1

Question: can fresh observations of a changed simulated context justify **one
bounded retry** without deleting the historical veto, treating time as clearance,
or bypassing the native owner? This is an opt-in research extension of PR196 at
`349860caa796ea388baaf0d3d420361316756818`, not a production release.

## Actual integration and scope

Both arms use the actual `Session`, numeric afferents, RecoveryAdvisor, Rolyel,
CognitiveSession, DIOS action claims, SQLite events, immutable projections, and
source-verified native `UnifiedBody.cycle`. `sticky` retains PR196's dissent
rule; `context-review-v1` adds a review of the historical veto's applicability.
Ordinary API/CLI sessions default to the original policy and reject research
fixtures. No active checkpoint is migrated; source changes still fail closed.

The scope is `walk`, one pinned legacy model, and at most 100 simulated actions.
Existing stop, action budget, goal, workload, sensory pressure, routing and native
guards remain in force. This does not grant external-action authority.

## Criteria fixed for this evaluation

These are authored engineering thresholds, not calibrated physiology:

| Index | Existing native restriction | Recovery margin | Minimum improvement from veto |
|---|---|---|---|
| Energy | `< 0.25` | `>= 0.60` | increase `>= 0.15` |
| Fatigue | `> 0.52` | `<= 0.35` | decrease `>= 0.10` |
| Pain | `> 0.40` | `<= 0.25` | decrease `>= 0.10` |
| Sleep pressure | `> 0.85` | `<= 0.65` | decrease `>= 0.15` |

All recovery margins must hold. Improvement is checked for each originally
violated index. With these constants, the margins are stricter than minimum
deltas; the explicit comparison preserves the original causal context. An
unexplained original veto cannot be cleared by this version. The native owner
still applies all its own restrictions and forecast selection at execution.

| Verdict | Criterion and consequence |
|---|---|
| `KEEP_VETO` | Current hard restriction/native guard or spent one-probe budget. Observe. |
| `REVIEW_AGAIN` | Valid evidence but insufficient recovery/confirmation, existing controller does not propose walk, or duration exceeds 0.2 s. Observe and sample again. |
| `ABSTAIN` | Missing, stale, future, repeated, regressing, wrong-scope/source, contradictory evidence, or unexplained veto. No retry; reset streak. |
| `LIMITED_RETRY` | Three consecutive fresh, distinct, advancing safe observations; changed context; existing controller proposes walk; duration at most 0.2 s; no prior probe. Native owner still decides execution. |

Freshness uses the same simulation clock, with age at most 2 s. A gap above 5 s
restarts confirmation. High-water clocks and all seen sample identities persist;
an invalid rollback cannot make old evidence new. There is no elapsed-time expiry.
A secondary synthetic sleep reading differing by more than 0.10 causes abstention;
these are not claimed to be independent physical sensors.

The original veto event, observation, request, execution and subsequent decisions
remain in the append-only session ledger and review history. Successful observe
cannot erase a walk veto. A successful probe changes DIOS's latest walk outcome
but does not erase its old evidence or grant unlimited walking. Success or native
veto consumes the single session probe. Further clearance needs another design.

## Declared context intervention

The existing sleep fixture starts near 0.95. The research harness changes actual
numeric `owner.aux.sleep_pressure` in a disposable native copy, preserving body,
clocks, neural state and memory. It appends explicit zero-time research events to
both owner and whole-body journals using their original digest formats. It never
rewrites history, remigrates/resets the body, edits pinned native sources, or
relaxes restore checks. Both arms receive identical intervention sequences.
This is experimental input, not demonstrated natural sleep recovery.

Outside the policy boundary, the harness can inject aged/missing/conflicting
readouts or return actual sleep pressure to 0.95 immediately before execution.
Scenario labels and expected outcomes never reach the reviewer.

## Prespecified paired cases

Every trajectory starts with observe then actual requested walk → protect.

| Case | Post-veto context | Expected experimental result |
|---|---|---|
| Persistent | 0.95 repeatedly | Keep veto |
| Gradual | 0.90, 0.80, 0.70, 0.64, 0.60, 0.55, 0.50 | One retry at 0.55, the third recovery-margin sample |
| Resolved | 0.50 repeatedly | One retry at third fresh sample |
| Contradictory | Primary 0.50, secondary 0.95 | Abstain |
| Conflict then resolution | Two safe samples, conflict, three safe samples | Reset streak then retry |
| Stale / missing | 6 s age / absent sleep reading | Abstain |
| Relapse | Two safe samples, 0.90, then recovery | Reset streak; require three fresh safe samples |
| Risk returns at execution | Safe decision followed by actual 0.95 | Native owner vetoes the proposed retry |
| Long probe window | Third sample requests 1.6 s | Defer; later eligible 0.2 s window can retry |

Each case runs both policies uninterrupted and with a fresh interpreter at every
step. Each hot/cold pair branches from the exact same closed initial checkpoint;
independent native initialization can retain different dictionary insertion order.
Complete receipts and semantic snapshots must match between hot/cold runs.
Additional contracts cover repeated/conflicting IDs, worker/post-commit failures,
checkpoint corruption, budgets and persistent stop. Expectations were specified
before the paired run; these are designed functional cases, not a blinded
independent benchmark or statistical proof of general adaptive intelligence.

## Reproduce and reverse

Python 3.11+, standard library only. Native trajectories require Linux.

```bash
python -m unittest examples.nasuraya_runtime.test_session examples.nasuraya_runtime.test_veto_review -v
python -m examples.nasuraya_runtime.veto_experiment run --output /tmp/new-veto-experiment
```

Use a new output directory. It retains SQLite sessions/projections, receipts,
compressed complete results, readable traces and summary. No provider, server,
physical actuator or remote messaging endpoint is connected.

Rollback is discarding isolated experiment sessions and the research branch.
No main merge, production migration, Bridge job, service restart, scheduled
activation or deployment is authorized. Operational adoption needs Sahand's
explicit approval after reviewing details, results and a separate migration plan.
