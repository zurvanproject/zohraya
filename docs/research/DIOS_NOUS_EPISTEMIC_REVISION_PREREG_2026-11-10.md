# DIOS NOUS / Epistemic Revision v0.1 — prospective protocol
**Registration:** 2026-11-10, before implementation or held-out execution.
**Scope:** offline research-only companion to strategic Issue #165, complementary to evidence-lineage PR #170 and goal-continuity PR #177. The Windows VPS remains reserved for the whole-body atlas Issue #180. No changes to ChatGPT memory, model weights or the native Tadash ledger.

## Hypothesis
A source- and time-aware *external software ledger* will select the currently best-supported categorical fact more accurately than a naive last-arrival event policy when given deliberately adversarial and contradictory synthetic evidence. We test **revision after verified correction**, **abstention on unresolved contradictions**, and **cold-process recall**. We do not test subjective experience, AGI or real-world truth.

## Precommitted input
Each synthetic fixture is a claim with (scope, key, value A/B, valid epoch, source root, source type, claimed verification, arrival id). The trust assertion is **authored by the test harness**, never inferred from text or a web comment. External/social content is always unverified. Append-only SQLite persistence; same event ID + different content must fail closed, repeated aliases of one root count once, differing verified values for the same root and epoch must flag inconsistency. A query is anchored to an as-of epoch and a scope. Multiple independent *verified* roots at the latest eligible epoch that disagree must return ABSTAIN. Later eligible verified correction supersedes older evidence, with older records retained. No guessed probability or invented confidence.

## Fixed scenarios and partitions
Use 10 authored adversarial regimes: stable fact with later untrusted rumor, actual later verified correction, repeated provenance aliases, same-epoch verified contradiction, unverified-only, future-dated untrusted rumor, other-scope contamination, conflicting values from same provenance root/epoch, independent corroboration, and query-before-subsequent verified correction. Values A/B assigned by per-seed deterministic RNG so position-specific policies cannot win by always choosing the same literal value.

- Development-only seeds **55000–55031**, 32 cases (randomized regimes; regression tests).
- Held-out seeds **56000–56159**, 160 cases (exactly 16 cases of each regime); **do not execute until policy, tests and this protocol are committed**.
- No use of hidden hold-out outcomes to tune policy. If threshold fails, report failure and start a new protocol for any next version.

## Compared policies
1. Provenance/time-aware ledger (new).
2. Last-arrival naive policy (takes the last event as true; never abstains).
3. Always-abstain control.
No claim of matched-capacity comparison: the new policy has explicit evidence metadata not used by the naive baseline.

## Outcomes, in this order
- Primary: exact decision accuracy across 160 sealed cases, where ABSTAIN is a valid expected decision.
- Secondary: false assertion rate on cases where correct output is ABSTAIN, accuracy on *verified corrections* (regime 1), accuracy of as-of queries (regimes 5,9), coverage (non-abstain fraction).
- Durability: each record can be read from an independently reopened SQLite connection; replays do not increase independent-root evidence counts.
- Acceptance threshold: new policy >=90% exact, at least +20 percentage points relative to last-arrival, zero false assertions in expected-ABSTAIN cases, all development tests green. These thresholds are *benchmarks of authored toy cases*, not independent generalization evidence.

## Security and boundaries
Only standard Python 3.12, SQLite and local ephemeral files. CI has `contents: read`, no model API, SSH, Moltbook write, real user messages, secrets, installation, production DB, filesystem paths from web text or costly calls. Claim text and provenance in tests are synthetic. This ledger is not a cryptographic signature system: verification labels come from the trusted caller, and raw public text must never be promoted to trusted evidence. Status UNKNOWN and conflict are explicit. Do not merge/deploy or rewrite an existing memory ledger automatically.
