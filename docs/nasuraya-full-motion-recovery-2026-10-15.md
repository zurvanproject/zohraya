# Full saved-boundary motion recovery

Base: PR #19, commit `89014b3cabc9820a61c9efcf80a3ae21ef661eac`.
The recorded private MotionGoal checkpoint was available. No synthetic
replacement was needed for the full-route evaluation.

## Observed result

The input was the accumulated-body reverse goal after seven confirmed landings,
at goal elapsed 94 s and native time approximately 294 s. A new uninterrupted
worker completed all 97 remaining ticks. A separate worker advanced the same
input for 26 ticks, saved after landing nine (elapsed 120 s, native time 320 s),
and terminated with `os._exit(75)` after fsyncing its checkpoint. A third Python
process restored that file and executed all remaining 71 ticks through closure.
The three workers had distinct process IDs; no live Python object was handed
between owners.

| Compared quantity | Uninterrupted | Stopped / fresh owner |
| --- | --- | --- |
| Confirmed route landings | 14 | 14 |
| Total native walk count, including prior forward route | 28 | 28 |
| Native time | 391.0000000000204 s | exactly equal |
| Fuel stock | 3762757.927117966 J | exactly equal |
| Reserve stock | 60000 J | exactly equal |
| Maximum model fatigue | 0.37427791065854943 | exactly equal |
| Goal phase counts: prelude / route / closure | 6 / 181 / 4 | exactly equal |
| Remaining route budget | 39 s | exactly equal |
| Final status | completed | completed |

Every request and full receipt digest in the uninterrupted suffix equals the
concatenation of the stopped and resumed traces. All landing receipts, cursor,
goal state, fatigue channels, budgets, energy stocks and clocks match exactly.
No actual instrumented physical substep was invalid. Final posture is double
support, with zero home error and balance index 1.0.

Final MotionGoal SHA-256:
`24670a78ce5861a74a3d2f023c46be4b814cd6f2eccf1eaad6563d941d15984a`

Final native checkpoint SHA-256:
`e2815f16bc14c8dfb4eac37ecc10dabdc4476ddd81910939ca5dbfe70d3fe4dc`

Both new endpoints also equal the recorded uninterrupted endpoint from PR #19.
The final checkpoint restores exactly in another process, and a terminal
`step()` rejects without changing it. All 72 tracked native files, the original
MotionGoal and the controller remain unchanged.

## Mid-action outcome handling

Bare MotionGoal still has no durable intent boundary. The added, opt-in
`MotionJournal` records intent before calling it and atomically commits the
full resulting goal and receipt in SQLite. It serializes owners and binds
duplicate requests to the original event ID and expected checkpoint digest.
Repeated committed requests return their receipt with no new time/fuel charge.

Six real subprocess exits were injected on both public synthetic and private
recorded-body fixtures: before execution after durable intent, in the third
actual native substep, after native cycle but before goal bookkeeping, after
the goal tick before commit, inside the final SQLite transaction, and after
commit before response. The first five preserve the old committed state and
an unresolved intent; further commands raise `UnknownMotionOutcome`. The last
recovers the committed goal/receipt and deduplicates the original request.

There is no automatic intent-clear or reconciliation operation. An unknown
effect cannot be retried through the journal. Independent authoritative outcome
validation is still required before designing a continuation for that case.
This is fail-stop protection, not demonstrated automatic mid-action recovery.

## Validation and reproduction

27 distinct tests passed, with no skips: 11 new public synthetic recovery tests,
11 versions on the recorded in-flight goal, and five existing public controller
guards. The two-concurrent-process retry test executed only one tick. Stale
writers, conflicting retries, corrupt goals and an existing destination reject.
CI now includes the public recovery suite. Remote CI success, if any, is separate
from these local results.

See `examples/nasuraya_star_motion/README.md` for commands. The evidence package
contains the input, stopped/final goals, full comparison traces, source hashes
and logs. Private body data are excluded from this repository.

Scope: deterministic process-stop/resume of this accumulated reduced software
model. The evaluation starts at the recorded seven-landing checkpoint; its
earlier history is preserved, not rerun here. It does not establish power-loss
durability, automatic unknown-outcome reconciliation, physical-actuator recovery
or unattended deployment. No live model/API call or official-body advancement.
