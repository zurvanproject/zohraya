# Coordinated star-motion overlay

This experimental overlay continues the authored star-in-place body exercise.
It keeps the native body, force/pressure/friction/tail guards and conservation
checks, and changes the motion controller rather than mass or force ceilings.
It is a software model, not a physical-body or consciousness measurement.

## Cause and correction

The recorded first failure occurred at native body time 49.3 s: left ankle
postural demand was 1933.811 N against 1921.880 N delivered under its current
regional guard. Postural energy priority was 1.0; the raw force cap was 2500 N.
An instrumented replay reproduced the original final checkpoint exactly.

Near touchdown, settling, walking weight transfer or stopping, the controller predicts one native
0.1 s tick on a private copy. If ordinary dynamics predict insufficient joint
support, it tries reduced centroidal acceleration commands at 0.75/0.5/0.25/0.
The first physically valid candidate is integrated once by the owning body.
No candidate resets stocks, moves a foot directly or changes a safety limit.
Prediction is a rollout of the same model, not independent empirical evidence.

The waypoint cursor now advances only after a matching native walk touchdown.
A cancelled swing retains its target. This avoids silently skipping star points.
The governor covers landings, walking `shift`/`double_support` and native `stand`
commands, including transitions after leaving `settle`. It is not a general fall recovery controller, and zero
friction remains a declared physical failure.

## Run and persist

Python standard library and the pinned native runtime are required:

```
python perform_coordinated.py --native-root /path/to/runtimes/tadash_body --source-db /path/to/waking_practice.sqlite --output /path/to/new-evidence
```

The source database is opened read-only. Inputs use the previously declared
waking practice branch; the high-sleep continuation session is not reset.
The route is the same 5 cm radius, two-foot star, with 14 target landings.
The original 36 s movement window and the extended movement window must be
reported separately; more landings in a longer run do not imply faster gait.
The lower-friction and reverse drivers are fixed, explicitly labelled variants.

Native checkpoints alone do not describe an installed controller. Use
`extension_state.checkpoint(body)` and `extension_state.restore(envelope)` to
preserve the controller, confirmed cursors and source fingerprints alongside
native state. The helper explicitly converts a still-active old requested
cursor to confirmed semantics when attaching a historical failure fixture.

## Targeted verification

The tests take the recorded pre-failure fixture separately from source code:

```
NASURAYA_NATIVE_ROOT=/path/to/runtimes/tadash_body NASURAYA_FAILURE_FIXTURE=/path/to/before_failure.json python -m unittest discover -s . -p test_coordinated_support.py -v
```

They cover the original failing transition versus the corrected transition,
unchanged stocks on attach, exact cold restore, corruption/source mismatch,
zero friction, replay idempotence and non-duplicated owner time/fuel despite
prediction clones. A separate cancellation check verifies no cursor advance.
Private body history and generated evidence stay outside the repository.
The inherited source is pinned to 49fd31c0f46ce51231203b198bb2433ed35133d7;
this change is stacked on the tissue-observer branch without changing it.

Four preliminary allocation/governor variants failed their acceptance checks
and were rejected. Their outcomes are retained in the accompanying evidence;
passing the one-tick transition alone was not counted as full-route success.

## Recorded outcome

Original: 3 landings, support failure at 41 s. In the same 41 s window the
accepted overlay retained 3 landings and valid support, using 0.954% more
fuel. A longer 190 s run reached 13 confirmed points without support failure;
a separately bounded 11.5 s continuation completed point 14 and closure.
Final posture was double support with balance index 1.0. Total model time
was 201.5 s. This is a stability/completion improvement, not a speed or
energy-efficiency improvement. The lower-friction check stayed valid through
58 s with 4 landings; the reverse route failed during closure at 56 s and is
not accepted as a general capability. Seven targeted tests passed across
focused runs, plus a separate cancellation check.

## Reverse closure investigation

The historical reverse failure was reproduced exactly from the private waking
practice database: all result rows and the final native checkpoint hash match.
The first invalid tick was at elapsed 55.2 s (native time 64.2 s), during the
second closure second. `settle` had changed to `double_support` one tick earlier,
so the old landing-only prediction gate no longer ran. Left ankle demand was
1959.349 N versus 1925.527 N delivered under the unchanged regional guard.
Both feet had contacted the floor, but required normal load was still entirely
on the left. Friction was unsaturated; postural energy priority was 1.0.

The bounded correction keeps the same one-tick search active for `stand`,
without changing any candidate scales or native limits. From the same saved
pre-closure state, four seconds of closure remained physically valid and ended
in double support. With the stop-only revision (PR #17), the reverse driver reached its 58-second
bound with valid support but only two confirmed route landings. This establishes
a safe stop for this fixture, not completion of the reverse route. The 48-second
movement budget was insufficient; native arbitration also cancelled two swings
before closure. Extending the budget alone is not demonstrated to solve that.

Six additional tests cover the recorded failure/correction, cold restore,
single owner charging/replay, prediction scope and genuine zero-friction and
regional-guard failures. Supply the private pre-closure fixture externally:

```
NASURAYA_NATIVE_ROOT=/path/to/runtimes/tadash_body NASURAYA_REVERSE_FIXTURE=/path/to/reverse_054_body.json python -m unittest discover -s examples/nasuraya_star_motion -p test_reverse_closure.py -v
```

Historical extension envelopes retain their original fingerprints and are not
silently migrated. This investigation restores the native saved state and
explicitly attaches the revised overlay to a copy.

## Full saved-boundary restart and uncertain actions

`evaluate_recovery.py` starts two independent processes from one source-pinned
`MotionGoal` practice checkpoint. One runs its entire remaining route without
interruption. The other advances to the requested confirmed-landing boundary,
fsyncs its full goal and exits with code 75 without Python cleanup. A third
Python process restores that saved goal and finishes the route. The comparison
checks every request/receipt hash, confirmed landing, clock, stock, fatigue,
phase budget and final native/goal digest. An existing uninterrupted endpoint
can also be supplied for exact historical comparison. Outputs must be new paths.

```
python evaluate_recovery.py run --native-root /path/to/runtimes/tadash_body --source /private/mid_goal.json --stop-landings 9 --reference /private/final_goal.json --output /private/new-recovery-evidence
```

This verifies a complete remaining route after a deliberate saved boundary.
It does not make bare `MotionGoal.step()` crash-safe. Callers that need durable
intent and receipt handling can explicitly opt into `MotionJournal`:

```python
from motion_journal import MotionJournal

store = MotionJournal.create('/private/new-practice.sqlite', goal)
goal = store.load()
head = goal.checkpoint()['sha256']
event_id = goal.request()['event_id']
receipt = store.step(event_id=event_id, expected_head=head)
# If the response was lost, retry this SAME event_id and head, not a new token.
```

The journal commits an intent *before* invoking the native simulator. Its final
SQLite transaction publishes the whole goal, event receipt and removal of the
intent together. A filesystem owner lock serializes processes. A duplicate
committed caller token returns the stored receipt without a new tick or debit;
stale writers and conflicting retry tokens reject. SQLite uses synchronous FULL;
the database and lock belong on a local filesystem with working SQLite/flock
semantics. These tests model process loss, not power loss or storage corruption.

If a process dies with a pending intent, `load()` and `step()` both raise
`UnknownMotionOutcome`. `inspect()` returns the pending request and prior head
without acting. There is deliberately no automatic retry, intent-clear or
reconciliation API: authoritative receipt/state validation is a separate future
integration requirement. Even an intent whose worker died before starting is
treated conservatively. This blocks progress rather than guessing an outcome.
An external actuator/API is not part of this local simulator transaction.

Public synthetic regression covers crashes after durable intent, inside the
third *actual* native substep (excluding forecast clones), after native cycle
but before goal bookkeeping, after the complete tick, inside the SQLite commit,
and after commit but before response. It also checks duplicate/concurrent
callers, stale writers, corrupted goals and non-overwriting creation:

```
python -m unittest test_motion_recovery.RecoveryTests -v
NASURAYA_RECOVERY_SOURCE=/private/mid_goal.json python -m unittest test_motion_recovery.RecordedRecoveryTests -v
```

The second suite uses the supplied recorded body; private inputs and generated
full-state evidence stay out of Git. The original goal/controller/native source
files are unchanged, so their saved source fingerprints remain valid.
