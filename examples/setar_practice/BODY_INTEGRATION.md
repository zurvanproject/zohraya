# Optional body orchestration bridge v0.4

This extends v0.3.1 without modifying its learned seed, audio engine, standalone
CLI, legacy body sources, or existing body host. It is explicitly invoked, not
a daemon or a default-enabled scheduler. No server, main-branch deployment,
external model, API key or paid API is used by this path.

## What is connected

`body_cli` reuses the native launcher's `verified_sources()` and copies that
source-pinned runtime into a temporary process directory. `body_worker` opens a
real `BodyLoop`, holding its existing file lock. `SetarBodyBridge` then uses the
same SQLite `meta` ledger for the skill binding, request reservations, receipts
and the current dedicated skill checkpoint.

A bounded request observes native state, checks declared engineering thresholds
for energy, hydration, fatigue, pain and sleep pressure, then asks the existing
native decision/feedback path for an **observe** cycle. Only a completed actual
`observe` and an acceptable post-cycle state permit one 10-second synthetic
audio exercise. `protect`, a different selected action, an unknown proxy,
read-only mode, an exhausted budget or unresolved work cannot start practice.

This is an orchestration gate, **not a new native play-instrument action**.
Native physiology advances 0.1 simulated seconds for the gate, not the full
10 seconds of audio. There is no hand dynamics, nail/string contact, calibrated
musical energy expenditure or synchronized audio/body clock. Readiness
thresholds are explicitly chosen engineering policy, not physiological facts.
Each request currently uses the existing first exercise (one episode); this
bridge does not pretend to schedule the full progressive 60-episode curriculum.

## Memory and retry semantics

Binding imports all inherited corrections once. The seed remains unchanged.
Budget counts attempted requests, including deferred and failed requests; a
restart cannot reset it. Binding an already bound session is rejected.

A request identity fixes its output path, timing mode and random seed. Replaying
a terminal request returns its receipt without a new body cycle or training.
A conflicting replay is rejected. A persisted `running` request blocks new work
until explicitly investigated; no automatic crash recovery is claimed.

The new skill checkpoint and successful receipt commit in one SQLite
transaction. Audio/filesystem output is not part of that transaction. On failure
the prior committed skill binding remains authoritative, although a native gate
cycle may already have occurred and output files may be incomplete. Evaluation
never updates skill memory or advances native body state. Direct database
editing or malicious filesystem replacement by the local owner is out of scope.

## Commands, from the repository root

```sh
python -m pip install -r examples/setar_practice/requirements.txt
python -m examples.nasuraya_body_loop start --session /tmp/setar-body-new.sqlite --fixture normal --max-actions 3
python -m examples.setar_practice.body_cli bind --session /tmp/setar-body-new.sqlite --max-steps 3
python -m examples.setar_practice.body_cli step --session /tmp/setar-body-new.sqlite --run-id lesson-1 --output-dir /tmp/setar-body-lesson-new --accelerated
python -m examples.setar_practice.body_cli status --session /tmp/setar-body-new.sqlite
python -m examples.setar_practice.body_cli evaluate --session /tmp/setar-body-new.sqlite
```

Use a fresh session/output path for this example. `--realtime` is an explicit
alternative to accelerated execution; the integration tests do not run a fresh
ten-minute wall-clock practice. A deferred step exits 2; rejection/failure exits
1. Successful commands and terminal completed replays exit 0.

## Verification layers

```sh
# Real audio engine + declared BodyLoop test double (not native-body proof):
python -m unittest examples.setar_practice.test_integration examples.setar_practice.test_body_bridge -v
# Actual body in the source-verified isolated process:
python -m examples.setar_practice.body_cli test
# Existing body-loop regressions, unchanged:
python -m examples.nasuraya_body_loop test
```

There are 21 pre-existing integration tests, 17 new contract tests and 5 native
integration tests. Counts here describe the suites, not an assertion that CI
has passed. Native success must be checked against the corresponding workflow
run. CI prints `NATIVE_SETAR_EVIDENCE` and `NATIVE_SLEEP_EVIDENCE` with measured
receipts. Independent review, full-repository regression and VPS deployment
are separate and are not implied by this optional adapter.
