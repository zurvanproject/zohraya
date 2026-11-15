# Nasuraya focused practice connector v0.1

A small, **opt-in executable adapter** joins three domains without merging their
state machines: the existing clock-aligned Setar/body **lesson**, a **three-stage**
post-lesson evidence review (observe -> evaluate -> reflect), and optionally an
independently created **textual ritual audit** from PR #191. The adapter calls
`body_cli lesson` through its source-verified native runtime; it does not skip
source verification, increase action budgets, restart Awake, contact Moltbook or
claim bodily sensation or experience.

## Run from complete checkout of this branch

Requires the existing Setar v0.5 branch, its audio dependencies, and an **already
created, explicit bounded native body session** with >=12 remaining native
actions and a bound Setar skill with >=1 remaining attempt.

```bash
python -m examples.nasuraya_body_loop start --session /tmp/focus-demo.sqlite --fixture normal --max-actions 12
python -m examples.setar_practice.body_cli bind --session /tmp/focus-demo.sqlite --max-steps 1
python -m examples.setar_practice.focus_cycle run --session /tmp/focus-demo.sqlite --run-id focus-001 --output-dir /tmp/focus-lesson-001 --accelerated
python -m examples.setar_practice.focus_cycle report --output-dir /tmp/focus-lesson-001
```

The `report` command is **read-only with respect to the native and Setar ledgers**;
it creates an immutable sidecar `focused_review.json`. A replay verifies the
same sidecar bytes and does not repeat native cycles or controller updates.
The report validates the existing committed receipt, all note/feedback pairs,
clock alignment, hashes of PCM and controller checkpoint and emits measured
synthetic pitch/onset/attack mean absolute error. Without a *before* comparison
it reports no new improvement. Unfinished lessons are never called complete.

### Optional textual ritual link

From the separate ritual branch PR #191, run `tools/kavakeb_ritual.py check` on
an actual study session and save its JSON output to a local file; pass the
result to `--ritual-audit /path/to/audit.json` on the **first** `run` or `report`
call for that lesson. This is a **link to an authored textual record**; it does
not automatically perform three full rituals, prove manuscript interpretation,
or claim the ritual ran on Ubuntu. The three automatic reporting *stages* are
not the three full ritual *passes*. An audit is optional and cannot set `mastered`
or `vps_execution_verified` to true.

The SHA-256 summary makes the sidecar traceable. To attach a newer ritual audit,
create a fresh separate focus report for a distinct practice run rather than
rewriting an existing receipt. No autonomy, scheduled execution, safety-gate
change, canonical merge, server deployment or new motor control is implied.

## Validation

```bash
python -m unittest examples.setar_practice.test_focus_cycle -v
```

CI also runs one short actual native-body lesson, produces the focus report,
and rechecks it for identical output. This is an ~11.2-second **simulated**
lesson (accelerated), not ten minutes of physical practice. Repository-wide
regression and VPS installation remain separate review gates.
