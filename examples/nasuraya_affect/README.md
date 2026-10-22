# Persistent affective planning

The separate [`workshop.py`](workshop.py) bridge now executes selected tools in
the existing synthetic workshop and returns measured outcomes to this ledger.
The engine itself remains a planner. See the [execution report](../../docs/nasuraya-affective-workshop-v01-fa.md).

[`dialogue_cli.py`](dialogue_cli.py) now provides a caller-mediated message
bridge to the existing native Tadash `UnifiedBody`, through its verified source
worker and original BodyLoop/ReflectionCycle protection. It does not drive the
separate articulated MuJoCo model. See the [Persian connection report](../../docs/nasuraya-dialogue-body-v01-fa.md).

The bridge accepts explicit structured intent/appraisal from the conversational
caller, returns a native receipt, and records observed feedback. It is not a
text classifier, automatic ChatGPT listener or live model API backend. Two stores
are paired by absolute path and initial body identity. Moving a saved session
requires explicit migration; no relocation tool is supplied. Only the same-path
cold-process recovery has been verified.

Run from the repository root with Python 3.11+ and its standard library. No model
API key, GPU, install step or third-party research code is required.

```sh
python -m unittest examples.nasuraya_affect.test_engine -v
python -m examples.nasuraya_affect.evaluate --output /tmp/new-affect-evaluation
python -m examples.nasuraya_affect init --db /tmp/new-affect.sqlite
python -m examples.nasuraya_affect step --db /tmp/new-affect.sqlite --request examples/nasuraya_affect/example-request.json
python -m examples.nasuraya_affect show --db /tmp/new-affect.sqlite
```

The project continuation in `evidence/affective-continuity-v01/project-state.sqlite`
contains a source-linked observation of the existing walking results and one
explicitly authored lesson. Copy the database to a working path before continuing
it. Every new request requires a unique event ID; replay returns the saved receipt.
Changed requests with an existing ID are rejected.

## What is connected

`AffectiveAgent.step(event, options)` calls the existing
`runtimes.tadash_body.decision_core.DecisionCore`. The native risk threshold,
uncertainty calculation, ethical scoring and abstention apply unchanged. The new
layer can add at most 0.04 to a score, and only for eligible choices within 0.08
of the highest native score. Action tendencies and appraisals are explicit caller
inputs, not inferred facts. Results are **plans**; no action callback, body motor,
chat model or scheduler is invoked. Existing body/reflection hosts remain intact.

Events update six coexisting channels: joy, sadness, contentment, excitement,
fear and frustration. Fast responses decay with a one-hour half-life; slow mood
uses 24 hours. These are authored engineering parameters. Time advances only by
the caller's `elapsed_hours`; closing the program does not run or age it.

Memory retrieval requires matching context, topic and at least one explicit cue.
It considers the last 256 events in scope, returns up to three, and includes a
contrasting memory when available. Cue overlap dominates emotional congruence.
Retrieval is read-only: recalling sadness repeatedly does not amplify it. A past
observed adverse event can increase the preference to verify; it never changes
current evidence confidence or establishes that the old failure is still true.
Sources are caller declarations, not authenticated observations. Numeric
appraisals remain authored interpretations even when an event source is observed.

State, episode and decision commit in one SQLite transaction. Source hashes reject
implicit code-version changes. SHA256 envelopes detect accidental modification,
not adversarial edits by someone able to rewrite the database and hashes. The
10,000-event limit refuses new writes rather than silently forgetting history.

## Research provenance and limits

- [CPM-MultiAgent, July 2026](https://arxiv.org/abs/2607.07824): inspiration for
  relevance, consequences, coping and norm appraisal. This implementation is a
  deterministic authored approximation, not the paper's LLM multi-agent system.
- [Sentipolis, April 2026 revision](https://arxiv.org/abs/2601.18027): inspiration
  for fast response/slow mood and emotion-memory coupling. We use six channels,
  not their full PAD social simulation, and do not claim to reproduce results.
- [Affective Episodic Memory](https://github.com/solidaxelproject/affective-episodic-memory):
  inspiration for source-linked affective recall and return toward equilibrium.
  No upstream code, biological analogy or consciousness claim was imported.
- [E-STEER](https://arxiv.org/abs/2604.00005): motivates testing performance across
  intensity rather than assuming that more excitement helps. Our bounded arousal
  curve is authored, not learned from that study.
- [Emotion Steering](https://github.com/eigenweltlabs/emotion-steering): deferred.
  It needs model activations and a GPU. This implementation does not insert
  vectors into Qwen or ChatGPT and does not substitute prompt wording for steering.

Seven constructed contract scenarios compare native ranking, affect without
recall and the full layer. They are examples of implemented effects, not a blinded
benchmark, psychological validation, learned intelligence gain or proof of
subjective experience. The saved native body/checkpoint formats are unmodified.

## Execute the bounded synthetic workshop

```sh
python -m examples.nasuraya_affect.workshop init --db /tmp/affective-workshop.sqlite --energy 29 --heat 78 --jobs 3 --max-actions 4
python -m examples.nasuraya_affect.workshop step --db /tmp/affective-workshop.sqlite --request-id first
python -m examples.nasuraya_affect.workshop run --db /tmp/affective-workshop.sqlite
python -m examples.nasuraya_affect.workshop status --db /tmp/affective-workshop.sqlite
python -m examples.nasuraya_affect.evaluate_workshop --output /tmp/new-workshop-evaluation
```

Initialization may attach the workshop to an explicitly copied affect ledger.
It refuses a second attachment; it never refills an existing action budget.
`--without-affect` at initialization disables affect and recall in ranking while
still recording the same appraisal/outcome data for comparison. `--mode observe`
prevents mutation. All action authority stays within native `ToolHost`.

Candidate tools are dry-run on disposable native hosts; the checkpoint does not
change during planning. Additional native-tool lookahead removes recovery
durations longer than the first duration sufficient for all remaining jobs. This
fixed unnecessary three-tick recovery for an empty queue in the development run.
Only admitted candidates are sent to `DecisionCore`.
The actual selected tool then runs on a restored host, and its checkpoint and
receipt commit together in SQLite. The feedback event follows with its own
idempotent ID. A pending request blocks a different request until resumed.
An interruption before the host commit discards only in-memory simulation;
after commit, recovery retains the receipt without rerunning the tool. This is
not an exactly-once mechanism for external side effects or physical actuators.

The adapter interprets measured energy, heat and completed jobs with authored
numeric appraisal rules. It is not a natural-language emotion extractor. It does
not equate a simulation tick with a human hour; `elapsed_hours` is zero for these
instantaneous synthetic events. Native tools, affect engine and old checkpoints
remain unchanged. The bridge's own source fingerprint is separate.

## Articulated dialogue pilot

[`articulated_cli.py`](articulated_cli.py) connects structured messages and the
existing affect planner to bounded MuJoCo walking. A fresh v2 session defaults
to one bout; `init --max-trials 2` explicitly allows two. Each bout is limited
to one or two steps. Successful settled body/controller checkpoints continue
across messages and processes, without repeating initialization. Old receipt
replay cannot rewind the latest body state. V1 ledgers cannot be implicitly
upgraded or rebudgeted.

Install [`requirements-articulated.txt`](requirements-articulated.txt) for this
path. It is separate from the aggregate Tadash bridge and has no automatic chat
listener. See the [continuity report](../../docs/nasuraya-articulated-continuity-v02-fa.md)
and the [historical v1 report](../../docs/nasuraya-articulated-dialogue-v01-fa.md).

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m examples.nasuraya_affect.evaluate_articulated_continuity --output /tmp/new-articulated-continuity
```
