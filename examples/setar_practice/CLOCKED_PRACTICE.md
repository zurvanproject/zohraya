# Optional clocked lessons v0.5

The new explicit `lesson` command closes two v0.4 gaps: one initial body gate
for a whole lesson, and always repeating exercise zero. Existing `step` behavior
and the 2,860-correction seed are unchanged. Neither command runs automatically.

## Clock and feedback contract

A lesson has a ten-second score plus 1.2 seconds for the audio tail. Eleven
1-second native `observe` cycles and one 0.2-second cycle therefore accompany
exactly 11.2 seconds of generated audio. Every window requires a fresh native
observation, acceptable declared readiness proxies, an actual completed observe
cycle and acceptable post-cycle proxies. The returned native timestamp must
agree with the audio sample boundary to within one microsecond.

This is **blockwise simulation alignment**, not sample-rate physiology, a
physical hand actuator, calibrated musical exertion, or live playback. The
native body approves a block before the synthetic audio events in it are
processed. No control response faster than one block is established. Audio
feedback is measured on isolated synthetic note stems, not the mixed output.
A note's correction is withheld until its full 0.82-second stem window is
available on the simulation clock. Later commands cannot use that future
feedback early. Generating a stem may compute future samples in advance; only
the declared availability event exposes its measurement to the controller.

In accelerated mode, simulation time is not wall time. `--realtime` also paces
these events against a monotonic wall clock; it does not establish real-time
hardware latency or represent continuous CPU use. No ten-minute wall-clock
practice is claimed by the integration tests.

## Durable course position and failures

A separate `clocked_curriculum_index` starts at zero on first use and selects
one of the existing 60 exercises, including string changes, short phrases and
alternating tremolo. Legacy training counts do not imply a historical position
in this new course. Only a fully completed lesson commits the controller,
completion receipt and next course position in the same SQLite transaction.
The course stops after lesson 60; it never silently wraps or enlarges budgets.
Old `step` commands do not advance this new course position.

A stopped lesson retains the previous committed skill and course position.
Native body cycles that already ran are **not rolled back**. Partial audio is
truncated at the last approved boundary; provisional corrections in a stopped
lesson are not imported into the binding. The receipt distinguishes body time
advanced from audio time approved. Successful alignment is not claimed for
these stopped runs. A fresh request may retry the same course lesson only with
remaining budgets; replay of the old identity returns its old result.

A crash leaving a `running` reservation blocks further work pending explicit
reconciliation. File exports are not part of the database transaction. The
SQLite binding and receipt, not a possibly orphaned output checkpoint, are
authoritative. Failure to export a convenience receipt after commit cannot
turn committed work into a redoable failure.

## Commands from a full repository checkout

Use new session/output paths. Do not alter a live ledger to refill its budgets.

```sh
python -m pip install -r examples/setar_practice/requirements.txt
python -m examples.nasuraya_body_loop start --session /tmp/setar-clock-new.sqlite --fixture normal --max-actions 24
python -m examples.setar_practice.body_cli bind --session /tmp/setar-clock-new.sqlite --max-steps 2
python -m examples.setar_practice.body_cli lesson --session /tmp/setar-clock-new.sqlite --run-id lesson-1 --output-dir /tmp/setar-clock-lesson-new --accelerated
python -m examples.setar_practice.body_cli status --session /tmp/setar-clock-new.sqlite
```

Every lesson needs 12 remaining native actions and one remaining skill attempt.
Insufficient budgets are rejected before reserving an attempt or making output.
The default three-action native session is deliberately insufficient. This
adapter never raises its configured limit. The native host's maximum 100-action
session can fit at most eight full lessons; long-course scheduling is outside
this change. The standalone legacy training path is not affected.

## Tests and evidence

```sh
python -m unittest examples.setar_practice.test_integration examples.setar_practice.test_body_bridge examples.setar_practice.test_clocked -v
python -m examples.setar_practice.body_cli test
python -m examples.nasuraya_body_loop test
```

The first command has 57 tests (38 retained plus 19 clocked contracts), using
actual audio and a **declared body double** for bridge contracts. The second
has 8 tests (5 retained plus 3 new) inside the source-verified **actual software
body**. It checks 24 native cycles, 22.4 seconds of body/audio alignment, cold
continuation without replay, insufficient budget, the sleep fixture and a
mid-lesson injected interruption. Assertions and suite sizes are not proof of
execution; consult the matching GitHub Actions run for pass/fail and measured
`NATIVE_CLOCKED_EVIDENCE` / `NATIVE_CLOCKED_INTERRUPTION` lines.

Full-repository validation, independent review, main-branch merge, VPS
installation, physical fingers, and nail/string contact remain separate.
