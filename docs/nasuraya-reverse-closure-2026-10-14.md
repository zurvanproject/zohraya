# Reverse star closure: failure cause and bounded correction

Baseline: PR #9, commit `14410b0ae2748ba51bf84d360b9189665c435974`.
PR #15 inherits that controller unchanged. Private checkpoints remain outside
the repository; all executions below used restored copies of the recorded
waking practice state, not the official API state.

## Comparison and reproduction

The forward order is `0,2,4,1,3,0,home`; the reverse order is
`0,3,1,4,2,0,home`, for each foot on a 0.05 m radius. Both use six seconds of
prelude and four seconds of closure, but their movement budgets differ:
180 seconds forward versus 48 seconds reverse. They are not equal-duration
completion comparisons.

The first two native touchdowns and states match. At elapsed 54 seconds,
forward has four confirmed touchdowns and no active swing; reverse has two
and a right walk swing at progress 0.66, height 0.09215 m. Reverse COM is
approximately `(0.196, 0.050)` m over the left foot; forward COM is
`(-0.2234, -0.04045)` m near the right foot. The left knee angles are 0.6351
versus 0.5090 rad; left ankle angles are -0.04782 versus 0.015995 rad.
Left ankle fatigue is 0.11450 versus 0.06814. These are native model states,
not anatomical measurements.

Reverse arbitration selected `slow_breath` despite requested `walk` at elapsed
40 and 48 seconds, cancelling near-complete swings. Only `walk` touchdowns
advance the confirmed cursor; `lower` touchdowns correctly do not. At the
48-second movement budget, the driver disables route targeting and requests
closure even though 12 route points remain. A longer budget alone has not been
shown to finish this route.

Historical reverse replay reproduces every result row and the final native
checkpoint hash exactly. The first failure is elapsed 55.2 seconds, native
64.2 seconds; the one-second receipt reports failure at elapsed 56 seconds.

## Immediate mechanical cause

Closure maps `slow_breath` to native `stand`, which lowers the active foot at
its current horizontal position. The foot lands at elapsed 54.6 seconds.
At 55.1 seconds, `settle` becomes `double_support`. At the next tick the
historical governor no longer predicts because it only covers `settle` or
late `walk` swing.

Although both feet touch the ground, the required normal load remains entirely
on the left. COM is `(0.189147, 0.048291)` m and velocity
`(-0.029504, -0.007360)` m/s. Desired COP is beyond the feasible left edge;
braking/pressure redistribution requests 1959.349 N at the left ankle but its
regional guarded capacity delivers 1925.527 N. Support fraction is 0.982738,
below the unchanged native 0.999 criterion. The raw 2500 N capacity and
0.770211 hazard cap explain the delivered value.

Friction demand is about 60.27 N versus 1147.77 N available. Friction is not
saturated, postural energy allocation is 1.0, no latch is active, and fuel is
about 99.05% of the initial stock. This is a genuine guarded support deficit
under that braking command, rather than exhausted energy or friction.
Holding upper joint targets constant still reproduces the failure. Continuing
walk for four seconds avoids this closure failure but still cancels another
swing; that is not evidence of reverse-route completion.

## Correction and validation

Keep the existing one-tick prediction search active whenever the native command
is `stand`, including `lower` and `double_support`. Nominal valid commands are
still integrated unchanged. Candidate scales, force/pressure/friction/tail
limits, protective locks and native validity criteria remain unchanged.

At the recorded failing tick, scale 0.75 still fails; scale 0.5 passes with
support fraction 0.999083 under the original criterion. From the same saved
pre-closure state, four seconds of corrected closure remain valid and end in
double support with final support fraction 1.0. The full corrected reverse
driver reaches 58 seconds with valid support, two confirmed touchdowns and
`star_complete=false`. This fixes safe stopping for this fixture; the reverse
route remains incomplete.

Seven existing and six new regression tests pass without skips when the
external recorded fixtures are supplied. They include legacy failure versus
corrected closure, exact cold restore, owner time/fuel and replay conservation,
zero-friction failure and severe regional danger/latch failure. All 72 tracked
native runtime files match the baseline byte for byte. Original input hashes
remain unchanged. No model/API calls or official body advancement occurred.

The tested simulator is a reduced, uncalibrated model. One-tick rollout is
same-model prediction; these results do not establish physical-body performance.
Historical overlay envelopes remain source-pinned and are not silently migrated.
