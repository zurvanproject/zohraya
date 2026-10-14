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

Near touchdown or native settling, the accepted controller predicts one native
0.1 s tick on a private copy. If ordinary dynamics predict insufficient joint
support, it tries reduced centroidal acceleration commands at 0.75/0.5/0.25/0.
The first physically valid candidate is integrated once by the owning body.
No candidate resets stocks, moves a foot directly or changes a safety limit.
Prediction is a rollout of the same model, not independent empirical evidence.

The waypoint cursor now advances only after a matching native walk touchdown.
A cancelled swing retains its target. This avoids silently skipping star points.
The algorithm is specifically a landing governor; it is not a general fall
recovery controller, and zero friction remains a declared physical failure.

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
