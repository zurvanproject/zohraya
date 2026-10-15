# Recover a verified completed motion outcome

At `3e704eb6280b7baeccbb78566a1ee89d60a632a7`, a process exit during
final journal publication left a pending intent and blocked the motion goal,
even though its tick had finished. The new journal persists a separate complete
outcome before publication. A fresh owner validates that result, publishes it
once and can continue the same goal without repeating the completed action.

## Measured before/after

Both versions were given the same private recorded nine-landing checkpoint,
with goal elapsed 120 s and accumulated native time 320 s. Both subprocesses
executed one complete ten-substep tick and exited with code 86 inside their
final SQLite transaction. The source was an isolated practice copy.

| Outcome after the same interruption | Previous journal | New journal |
| --- | --- | --- |
| Pending tick can be published | No; blocked | Yes; verified outcome |
| Committed progress after recovery | 0 ticks | 1 tick |
| Native actions during reconciliation | 0 | 0 |
| Further continuation demonstrated | Blocked | 2 additional ticks |
| Exact match to an uninterrupted three-tick copy | No advanced state | Yes |

The new saved practice state advances from approximately 320 to 323 native
seconds and goal elapsed 120 to 123. Fuel decreases from 3805842.2317788783
to 3804218.1931853215 J. Its checkpoint equals the uninterrupted endpoint:

`f090f725abf4ff3d77033e7e22b0c36993db7fe97b753ac89ee6b1437177447e`

Native execution and physical integration were patched to raise throughout
reconciliation; the successful recovery therefore did not repeat either a
native cycle or a model rollout. Retrying the original caller token returned
the identical receipt without additional progress or fuel debit.

## Validation contract

`recover()`, `load()` and `step()` can reconcile a complete saved outcome.
Validation checks checksum, journal source fingerprint, pending request, prior
checkpoint, pinned body/goal sources and the native cached request/receipt.
The original MotionGoal bookkeeping is reused through a receipt-only adapter
and must reproduce the entire claimed goal envelope exactly.

Tests cover seven process-exit boundaries, duplicate/concurrent callers and
recovery owners, stale writers, corrupted goal state and five kinds of invalid
outcome: checksum, request, receipt, goal transition and source mismatch.
Public synthetic and private recorded-body suites use the same contracts.
The inherited controller guard tests remain included in CI.

35 distinct local tests passed with no skips: 15 public synthetic recovery
tests, the same 15 on the private recorded goal, and five inherited controller
guards. The before/after subprocess comparison is additional executable
evidence, not included in that unit-test count.

## Boundaries

This improves availability after a completed **durable local software-model
outcome**. A missing/partial outcome, including a crash during native execution
or before recording the completed goal, still blocks. There is no blind retry
or intent-clear operation. Checksums do not authenticate arbitrary external
producers; external actuator/API reconciliation is outside this transaction.
Power-loss behavior and a full-route trial with this new journal were not
evaluated. The earlier full-route evaluation belongs to the parent commit.

Schema 2 journals are newly created; existing schema 1 stores reject without
implicit migration. MotionGoal, the controller and all 72 tracked native files
remain source-identical, preserving existing checkpoint compatibility. The
practice checkpoint advanced; the official state and live API were not used.

See `examples/nasuraya_star_motion/README.md` and
`compare_outcome_recovery.py` for reproduction. Private databases, checkpoints,
comparison results and logs are saved in the accompanying evidence package.
