# NASURAYA Offline Replay Audit — delivery pilot

Turn a bounded, sanitized execution trace into a reproducible review of retry,
completion and reported-cost anomalies. This is the trace-analysis component of
the earlier Offline Replay Audit service concept, not a replacement for the
Continuity Kit, the runtime or the existing scheduler.

**Status:** working local delivery tool; no customer order, paid deployment,
payment integration or demonstrated revenue. No third-party code was imported.
The repository's licensing decision remains separate from this service pilot.

## Run

Python 3.11+; standard library only. No installation, network, model API or
credentials needed. From the repository root:

```bash
python3 services/replay_audit/audit.py services/replay_audit/sample.jsonl --budget-minor 100 --currency USD --format markdown
python3 -m unittest services.replay_audit.test_audit -v
```

The sample is entirely synthetic. Its cost numbers are test fixtures, not
project expenditure. It deliberately has a reused request, a repeated effect,
a reported-cost overrun and an unfinished run. `SAMPLE_REPORT.md` is generated
from it. Findings point to source line numbers without copying identifiers.

## Input contract

UTF-8 JSON Lines, at most 2 MB and 5,000 events, chronological with timezone.
Required fields: `at`, `kind`, `run_id`, `request_id`, `cost_minor`.
`kind` is `start`, `finish`, `fail` or `effect`. Only `effect` requires and
permits `effect_id`. Identifiers are pseudonyms of 1–80 ASCII letters, digits,
underscore, dot, colon or dash. Unknown fields are rejected to discourage
accidentally including payloads or prompts. This is not a secret scanner.

Each attempt has one unique `run_id`. Retries of one logical request share
`request_id`. One external operation shares `effect_id` across attempts.
The auditor flags even legitimate request reuse for review; it cannot determine
whether a retry was justified. `cost_minor` is a nonnegative integer *increment*
in one operator-specified currency, not a cumulative total. USD uses cents.
Zero budgets are valid. There is no currency conversion or crypto pricing.

Export the complete chosen time window and remove prompts, API keys, personal
data, customer names and payment details before review. The tool does not
ingest OpenHands, LangGraph or provider logs directly: map them into this schema
first. Do not send private traces to a public repository or CI artifact.

## What the customer receives

1. JSON and readable report identifying observed trace inconsistencies.
2. Source-line references and input SHA-256 for reproducibility.
3. A short prioritized remediation note, with uncertain findings labeled.
4. One repeat check of the same scope after correction.

This does not execute customer code, inject a crash, prove exactly-once effects,
verify real bills or certify security. Partial logs can produce orphan or
unresolved findings. A repeated log entry is not proof of a repeated charge.
A broader code-level crash/restart audit needs a separately agreed scope.

## Proposed first commercial experiment — not an active checkout

Target: one developer or small team operating background jobs or coding agents.
Scope: one sanitized trace, one currency, maximum 5,000 events, report and one
recheck. Proposed pilot price: USD 29, retained as a **pricing hypothesis** from
the previous service concept; not evidence of market demand or a promised sale.
Agree delivery timing after inspecting a sample. Code fixes, hosting and
production access are excluded from this small offer and require a new quote.

Before accepting a paid order, establish an operator-owned, provider-permitted
payment route and the responsible contracting person. A payment processor's
general cashout page is not confirmation of this project's eligibility.
Do not create false location or identity information to obtain an account.

Work can now be delivered locally without model charges. Customer acquisition,
payment verification and any outbound pitch remain unperformed. The next
commercial acceptance test is one real customer accepting the scope and a
verified payment route, followed by an actual paid delivery. Building more
internal modules is not a substitute for that test.

## Operating economics

Measure: cash received minus refunds, collection fees and actual delivery
expenses. Track operator time separately. Do not count quoted work, repository
stars, test tokens or pledged bounties as revenue. Required jobs for a target
monthly cost C are `ceil(C / net_margin_per_completed_job)` only after the net
margin is measured; no income projection is claimed here.

The current tool has no daemon, wallet, purchasing, external posting or scheduler
integration. Scheduled research/test workflows in the wider project do not
make this service an autonomous business.
