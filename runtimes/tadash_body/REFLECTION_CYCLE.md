# Reflection Cycle v0.1

This additive wrapper connects the recovered DecisionCore v0.1 to the latest
recovered UnifiedBody v2 software bundle. Native body equations and historical
body/memory schemas are unchanged. The task ledger is a separate SQLite file.

## Request and outcome

Each request declares a context, topic, goal, hard goal constraints, timestamp,
source-linked evidence and candidate actions. Evidence carries `observed`,
`inference` or `authored` provenance. Only fresh observed evidence can satisfy
an action's explicit evidence requirements or exact factual claim contracts.
This is structural validation of declared data, not authentication of a source.

The existing DecisionCore first evaluates scores and its risk gate. The wrapper
then excludes unmet evidence requirements, unsupported/contradictory claims,
required-goal conflicts and unavailable required tools. Among remaining actions,
it subtracts a fixed 0.6 preference penalty after a verified negative outcome of
the same semantic action signature, exact context and topic. The latest verified
success clears that penalty. The constant is an engineering policy, not a fitted
probability or a manuscript-derived law. A low-ranked action can still be chosen
if it is the only eligible option. Recent retrieval is limited to 128 records;
the ledger retains up to 10,000 decisions and then refuses new insertions until
an explicit retention/expansion decision is made.

`decide()` persists the goal, evidence/locators, unknowns, all evaluations and an
expected outcome before execution. `execute()` invokes an explicitly supplied
Python callback and records its actual returned result or caught exception.
`complete()` atomically commits outcome and verification feedback. Unverified
feedback is retained but does not change preference. Matching is exact for the
expected outcome's top-level keys; no semantic grader or language model runs.

## Body connection and recovery

`ReflectiveBody.cycle()` restores the saved body, invokes its existing
`UnifiedBody.cycle()` and commits the returned body checkpoint and cognitive
feedback in one SQLite transaction. The native body's own veto and conservation
checks remain in force. No physical actuator or network service is installed.

Identical completed requests return their existing receipt without reexecution.
Altered requests with the same ID are rejected, including altered body clock,
duration or external input. A crash after marking execution `running` leaves an
unresolved operation: inspect the external result and call `complete()` explicitly.
No automatic callback replay is allowed. This is sequential body orchestration;
concurrent body execution, arbitrary external actuator exactly-once semantics,
producer authentication and resistance to OS-level database edits are outside
this version. SQLite commits provide crash-safe local persistence, not remote
replication. Export/backup is required for portability.

Existing source-pinned body checkpoints still require the matching original
runtime. No old checkpoint or user database was reset, auto-migrated or loaded
into a synthetic experiment. The recovered old continuity databases were opened
read-only for integrity checks; several old runtime modules referenced by their
historical README are absent from that partially recovered archive.

## Reproduce

Linux, Python 3.11+, standard library:

```sh
python3 run_tests.py --reflection --output /tmp/tadash-reflection-check
```

Choose a new output directory for a new demonstration:

```sh
python3 run_reflection_evaluation.py --output /tmp/paired-reflection
python3 run_reflection_demo.py --output /tmp/new-reflection-demo
```

The full runner copies verified source files into an isolated temporary tree and
creates explicitly synthetic fixture defaults there. It includes the old body
regressions, the recovered decision-core tests, new reflection/restart checks,
paired frozen-scenario evaluation and a body-feedback demonstration. `--endurance`
and `--special` retain their previous optional scopes and are not implied by
`--reflection`.

A saved ledger can be queried in a new process without regenerating a body:

```sh
python3 reflection_cli.py --db /path/resume_checkpoint.sqlite export
python3 reflection_cli.py --db /path/resume_checkpoint.sqlite decide --request /path/new_request.json
```

For an existing stored body, use the API explicitly:

```python
from reflection_cycle import ReflectionCycle, ReflectiveBody
with ReflectionCycle('/path/body_with_memory.sqlite') as engine:
    adapter = ReflectiveBody(engine)
    receipt = adapter.cycle(request, at_utc=request['at_utc'], duration_s=0.1)
```

## Evaluation interpretation

`reflection_cases.json` and its SHA256 were frozen before implementation. Ten
constructed scenarios use the same action scores in all three conditions: the
unchanged core, the wrapper without recall, and the wrapper with recall. Five
cover the requested failure types; five check that legitimate/creative actions,
scope changes and the original risk gate are not suppressed indiscriminately.
The old and new selectors share the same externally supplied numerical estimates.
These are deliberate contract fixtures, not a blinded natural-language benchmark.

The body demonstration uses a recorded synthetic sleep-pressure intervention.
Its first walk request is vetoed by the existing body. Without recall it repeats;
with recall the next requested body action becomes observation. Returned body
outcomes are actual software executions; they are not observations of a physical
body. The project ledger separately retains a retrospective, source-linked
manuscript correction and the unfinished book commitments. No fresh full OCR
or book completion is implied by this intervention.
