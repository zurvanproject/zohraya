# Continue a route goal on the accumulated body

Parent: draft #18, executable controller commit
`9a5386887cc814940dddef2732f366a6cf8e32bd`. Its forward and reverse evaluations
each completed 14 native touchdowns from separate identical practice copies.
This extension reuses the saved *end* of a completed route and starts the next
goal on its actual accumulated native time, stocks, fatigue and history.

`MotionGoal.start` requires a completed, settled prior route. It stores the
prior controller cursor and checkpoint digest, then creates a separate goal's
targets/cursor. Native checkpoint equality is checked across that operation.
An incomplete goal cannot be silently discarded; repeated goal identifiers
are rejected. The native controller and all 72 tracked runtime files are
unchanged.

## Persist the goal with the body

The explicit goal envelope contains the native/controller envelope plus goal
identity, direction, home, confirmed touchdown receipts, phase, elapsed time,
per-phase counts, consecutive veto count and terminal outcome. The same bounded
contract is retained: 6 seconds prelude, up to 220 seconds route and 4 seconds
closure. New task counters never refill the body's stocks or reset its clock.

Goal/native time, revision, cursor, confirmed target coordinates and activation
must agree. Restoring malformed budget/state, a corrupted checksum or different
goal-module source fails before issuing another native command. The next
request is generated deterministically from the saved phase and remaining
budget. This supports intentional saved-tick handoff, not arbitrary mid-tick
process crashes, asynchronous actuator recovery or unattended deployment.

## Bounded chain evaluation

`run_route_chain.py` opens the recorded completed forward endpoint read-only
and continues reverse motion on that copy. At seven newly confirmed landings,
it saves the goal, executes the next tick on the continuing owner and replays
the saved goal's tick in a fresh Python process. Full receipt and goal
checkpoint digests, next request and remaining counts must match. The extra
cold-validation tick belongs to a private clone, not the continuing owner.
Owner time/fuel accounting is checked separately from that clone.

Invalid actual support stops the goal. Three consecutive native walk vetoes
or an exhausted route budget trigger bounded closure and preserve an incomplete
outcome. Completion requires all target landings, exact home return and double
support; it is never inferred from issued commands alone.

Five new recorded-fixture tests pass: no native mutation on new-goal creation,
rejection of incomplete predecessors, saved-tick request/outcome/budget and
owner-time equality, budget/checksum/source corruption rejection, and a declared
synthetic high-sleep copy that retains the native veto and closes an incomplete
goal after exactly 6 prelude + 3 vetoed route + 4 closure seconds. The
eighteen parent controller tests retain their previous evidence; the controller
itself is byte-identical to that tested parent. Public CI still tests the five
synthetic controller contracts; the private goal tests are run locally.

```
NASURAYA_NATIVE_ROOT=/path/to/runtimes/tadash_body NASURAYA_CHAIN_SOURCE=/path/to/completed_forward_checkpoint.json python -m unittest discover -s . -p test_motion_goal.py -v
python run_route_chain.py run --native-root /path/to/runtimes/tadash_body --source /path/to/completed_forward_checkpoint.json --direction reverse --output /path/to/new-chain-evidence
```

All body data remain private. The tests use the same reduced, uncalibrated
software model; no model/API calls or official body advancement occur.
