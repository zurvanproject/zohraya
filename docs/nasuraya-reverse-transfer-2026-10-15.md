# Reverse star continuation: why the third landing was cancelled

Parent: draft PR #17, commit `f4923538738942285d27fd7a8cd4eb784d4c419d`.
That revision fixed the final `stand` failure but left the reverse route at two
confirmed landings in its 48-second movement window.

## Observed cause and correction

On a copy of the saved pre-closure state, continue the requested walk with
unchanged upper targets. After two seconds, the owner forecasts a right
touchdown followed by `settle` and walking weight transfer. In `shift`, the
stop-only controller drops the prediction gate: left ankle demand is 1959.349 N
against 1925.527 N delivered by the existing regional guard. The native owner
correctly predicts invalid support and selects `slow_breath`, cancelling the
swing before the actual touchdown. This is not an arbitrary refusal to walk.

Keep the existing acceleration search active during native walking `shift`
and `double_support`. No native arbitration, penalty, requested-action bonus,
force/friction/pressure/tail limit, protective latch, or support-validity
threshold changes. On the exact same one-second pre-veto fixture, the
historical scope forecasts invalid walking and chooses slow breathing with
cursor L=1/R=1. The revised scope forecasts valid walking and the native
selector chooses it, recording the third matching landing, L=1/R=2.

The matching waypoint cursor still advances only on actual native `walk`
touchdown. Cancelled and protective/lowering steps cannot count as completed
star targets. Feasible nominal transfer frames and native checkpoints match
the previous controller exactly. Prediction clones do not charge owner time
or fuel; cold-restored outcomes are identical.

## Frozen full-route evaluation

`run_bounded_route.py` opens the original waking-practice database read-only,
restores a copy and explicitly attaches the revised overlay without altering
its native stocks. Forward and reverse get identical 6-second preludes,
220-second maximum movement windows and 4-second closures. Each radius is
0.05 m, with seven prescribed targets per foot including the return home.
The actual used time and confirmed coordinates are recorded, not inferred
from an issued swing command or a total step count.

The evaluator stops on invalid support or three consecutive native walk vetoes
and retains the outcome. It checks touchdown order, controller source integrity,
input database integrity and exact cold restore. A separate inventory verifies
all tracked native runtime files. No controller or native source edits occur during
an evaluation: source fingerprints are captured before stepping and rechecked
afterwards. A larger budget than the historical reverse 48-second window is
explicit; the matched one-second regression isolates the controller correction
from that budget change. General gait speed, smoothness and physical-body
performance have not been established by this reduced uncalibrated model.

## Regression evidence

Eighteen distinct local tests passed: the previous thirteen plus five transfer
tests. These include paired native selection, verified touchdown, exact cold
restore, time/fuel accounting, unchanged feasible nominal transfer, reverse
route construction, and a declared synthetic high-sleep intervention on an
isolated copy. The native sleep gate still excludes walking; zero friction
and severe regional danger remain real failures. All 72 tracked native runtime
files remain byte-identical to the parent. No API calls or official body
advancement occurred.

The added CI job runs five public synthetic tests without private checkpoints.
The recorded regression fixtures remain outside this public repository.
