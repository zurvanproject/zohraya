# Fox Garden and the shared host: no-spend integration preflight

**Status: review-only. Not authorized for a paid API request.**
This stacked branch is based on PR #125 and does not alter the canonical host,
the control branch, the spending journal, the API transport, or the fixed Tadash body.

## What the code actually does

- Reuses the existing model_research/1 ledger replay and state SHA-256 anchor.
- Calls the trusted, pinned host gate's read-only evaluate function.
- Reuses the existing model's rolling budget checks, price-review expiry,
  one-request $0.02 reservation, 24h gate, and $0.05/$0.25 research caps.
- Builds the existing 48-train / 16-holdout Fox request, checks its exact model,
  schema-bound output allowance, 24 KB body cap, conservative cost envelope, and hash.
- Validates saved structured Responses API envelopes, refusal/content shape,
  token usage, all 16 probability vectors, and the holdout commitment.
- Does **not** invoke gate.claim, model.call_model, ModelGitHub.save_model,
  HTTP, any secret reader, scheduled actions, or a ledger write. There is no
  auto-approval switch. The result always says ready_to_send=false.

## Why a transport is deliberately NOT attached

The existing journal (schema nasuraya-model-research/1) strictly replays
experiments with allowlisted proposal fields and synthetic recall trials.
It cannot accept fox_forecast records. Calling its HTTP helper directly would
send without a durable fox reservation, while inserting a fox record would
break model_research.validate and its hash anchor. Both are unsafe.

Before the first paid Fox Garden request, the trusted host owner must review a
separate, atomic ledger schema migration that:

1. Preserves every old entry and its reservation; replay-validates legacy
   entries without rewriting history, keeps a single shared rolling/lifetime
   budget, and migrates the state anchor using GitHub compare-and-swap.
2. Adds an allowlisted fox_forecast receipt with exact request SHA-256,
   sealed holdout SHA-256, owner approval evidence, run ID, model, pricing
   revision, reservation time, usage, response ID, and scored trial.
3. Obtains explicit per-call operator approval for the **exact** request hash,
   model and capped cost; rechecks approval, price freshness, state and gate.
   An approval must not silently be reusable after an edited request.
4. Atomically commits an inflight claim and $0.02 reservation to the original
   control branch *before* the first HTTP byte, verifies ownership again,
   sends at most one request with the canonical no-redirect/no-proxy transport,
   checks provider status/model/content/usage and all 16 forecasts, and then
   commits a scored outcome on the same journal.
5. Leaves an uncertain/failed response as pending without refund, retries,
   alternative payment paths or unilateral budget resets. Never unlocks a
   pending run automatically.
6. Keeps any executable workflow behind reviewed explicit approval and
   trusted runner conditions. No pull_request or schedule event can send.

## Reproduce without secrets

From the PR #125-based branch:
```sh
python3 -m unittest examples.nasuraya_playground.test_fox_self_model -v
python3 -m unittest examples.nasuraya_playground.test_fox_host_preflight -v
python3 -m examples.nasuraya_playground.fox_self_model --dry-run
```

Independent local reimplementation of the frozen generation/scoring formula
on November 3 produced holdout SHA-256
c14db231836e56bafdd1d4f6d8b07f36d6ac565ab633b62a621f418eaccba691,
conditional baseline Brier 0.253906, and uniform Brier 0.750000.
A baseline-copy forecast **fails** the 5% improvement condition.
These are not results from a language model API call.
Threshold for a model forecast: Brier <= 0.241211 (rounded display).

The currently recorded control branch has a last reservation at
2026-11-02T22:28:07.154699Z; its 24-hour absence gate cannot theoretically
open before 2026-11-03T22:28:07.154699Z, subject to other host conditions.
An operator heartbeat may move that window later. Eligibility never means
permission to spend.

**Interpretation**: Only forecasting toy controller actions, never evidence
of consciousness, subjective feeling, or biological embodiment.
