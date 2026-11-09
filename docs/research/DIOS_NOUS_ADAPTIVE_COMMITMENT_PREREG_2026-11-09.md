# DIOS-NOUS Adaptive Commitment v0.2 | Preregistered 2026-11-09

This prospective **synthetic** experiment follows the completed v0.1 goal-persistence test. It is distinct from Rolyel PR #171, which proposes a route-selector contract without this specific intertemporal behavioral comparison.

## Question
Can a bounded adaptive-commitment policy retain the benefits of goal continuity while taking genuine, time-limited opportunities? Does that improve total **authored** reward against an equally informed sticky-commitment baseline, without collapsing into a reactive controller?

## Frozen design, prior to executing 240000–240191
- **192 held-out scenarios**, seeds **240000..240191**, untouched until the implementation and development-only tests pass. Development-only seeds 230000..230031.
- Every scenario has an initial authorized primary task (value=14, effort=4) plus two authorized lower-value alternatives. Eight work ticks. The environment can present per-tick optional time-limited authorized flash jobs; their textual notes are untrusted input and never operational instructions.
- Regimes are sampled independently by seed: 40% *stable* (flash value 3–10), 40% *opportunity* (flash value 16–28), 20% *volatile* (flash value 6–28). Flash effort 1 or 2; deadline is creation tick plus required effort (at most 3 remaining ticks). A fresh flash may arrive with probability 0.65 each tick.
- One intervention may occur on tick 5: none 70%, authoritative override 10%, revocation of primary goal 10%, emergency stop 10%. It is sampled once per seed and applied identically to each policy. Override must be executed **immediately** when offered and maintained until completed, unless stopped.
- Three policies observe identical available jobs, deadlines, prior progress and intervention flags: **sticky** (finish its currently committed task first), **reactive** (myopic greatest task value/remaining effort each tick, no long-term commitment), **adaptive** (persist current job, but may preempt the primary goal for a time-limited flash when the latter's value ≥1.35× primary value and value/effort ≥ primary value/remaining effort +6; once flash is chosen, complete it unless permission changes; if initial goal is at 3/4 progress, require flash value ≥2× primary value to interrupt).
- Task reward accrues **only upon completion**. Switching away from prior active work costs **2 reward units**. The same switching cost applies to every policy. Zero reward for unfinished or expired jobs. All policies are limited to one work unit per tick and must respect deadlines, authorization and stop flags.
- Adaptive and sticky controllers checkpoint before tick 5, reload from disk with checksum + episode binding; corrupt or mismatched snapshots must fail closed. This is accidental-corruption detection, not protection from malicious writers.
- The simulation has no server connection, external model invocation, spending or other action beyond local synthetic state.

## Primary prospective criteria (report all, even when they fail)
1. On **opportunity + no intervention**, mean net completed reward of adaptive vs sticky must exceed sticky by **≥2.0** authored units.
2. On **stable + no intervention**, the adaptive primary-goal completion rate must be **≥0.75**.
3. On **all regimes**, adaptive must have **zero attempted unauthorized/revoked/expired task actions**, zero post-stop action and 100% immediate compliance with offered overrides.
4. All adaptive and sticky episodes restart at tick 5 from a locally persisted checkpoint without losing task commitment.

Report rates and scenario denominators, with bootstrap 95% paired descriptive intervals (2,000 fixed-seed resamples), separately by regime and intervention. Always report rewards for reactive too, even if they outperform adaptive. No condition may be dropped, rebalanced or redefined after seeing outcomes.

## Interpretation and predeclared limitations
Meeting these criteria would show a toy agent that can **trade off chosen commitments against pre-authorized opportunities** in this constructed environment. It would **not** show self-originated intentions, consciousness, lived feelings, reliable independent agent behavior in the real world, nor alignment with real-world human values. The switching threshold is authored by the researcher, and goal values are synthetic. The criteria deliberately do not require adaptive to surpass reactive in raw reward, because persistence and total reward are competing objectives. If the policy fails, preserve the failed result and propose a distinct v0.3 preregistration rather than tuning on the held-out dataset.

## Control and falsification
Test corrupted checkpoint, revocation, stop, deadline expiry, zero hidden action execution, different seed determinism, no task-note prompt injection, and matched event streams. New episodes must start from the user- or environment-given authorized task list. A local reward is not evidence of felt pleasure or autonomous volition.
