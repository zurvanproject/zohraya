# Persistent affective planning

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
