# DIOS NOUS v0.2 | Equal-Information Falsification + Integrity Check
**Preregistered 2026-11-10, before writing v0.2 code or executing its held-out seeds.** Follow-on study in draft PR #182, extending but not rewriting the frozen v0.1 result. Owner's Windows VPS continues to own the whole-body mission in Issue #180; no server job is authorized by this research.

## Question and explicit falsification target
The 160/160 (100%) v0.1 result used a weak last-arrival baseline denied the metadata available to the new ledger. To avoid mistaking an information advantage for cognitive learning, give an **independently implemented reference policy the EXACT SAME records and metadata** as the SQLite ledger: scope, claim key, source root, source kind, caller-supplied trust flag, valid epoch, arrival identifier, and as-of time.

**Prediction before evaluation:** a straightforward equal-information, nonpersistent list reducer will likely match the v0.1 ledger on these rule-authored A/B fixtures. If scores tie, state plainly that v0.1 provides *no demonstrated decision advantage over this fully informed reference*. What it additionally implements is append-only/idempotent persistence and the ability to audit externally pinned snapshots. The reference is not trained and does not need SQLite. A tied result is an important scientific correction, not a failure to report.

## Fixed policies and outcomes
- P1: v0.1 `EvidenceLedger.resolve` with SQLite persistence, unchanged code.
- P2: new **independent list-only matched-metadata comparator**, same trust, time, scope, provenance and conflict inputs. No call to P1's resolver, no learned parameters and no access to expected label.
- P3: original naive last-arrival baseline (acknowledged as metadata-disadvantaged).
- P4: original always-abstain baseline.

Each v0.1 fixture deterministically assigns A/B labels and authored verification flags. The ground truth is built into the authored fixture and must NOT be construed as independent real-world truth.

## Fixed partitions
- Development-only seeds: **610000–610039** (40 examples, four for each of the v0.1 ten regimes).
- Held-out-first-run seeds: **620000–620159** (160 examples, sixteen for each regime).
- Same original `fixture(seed)` generator as v0.1, no tuning on holdout, no posthoc threshold changes. Registered before writing/evaluating v0.2.
- Every seed: compare exact decision and abstention, count outcome mismatches between P1/P2, close/reopen SQLite and compare again.
- Metamorphic test: deterministic reorder of the same evidence and one alias with a new event_id but identical original root/value/epoch must **not** alter P1/P2 result. No claim that naive last-arrival is order invariant.
- Integrity: for every held-out seed, snapshot the canonical, sorted rows, retain the SHA-256 digest **outside a disposable copied database** as a fixed anchor, flip one synthetic value in the copy via direct SQL, assert digest mismatch. This checks *accidental-data-corruption detection relative to an independent anchor*; it does NOT detect an attacker able to rewrite both database and anchor.

## Preregistered reporting and gates
Publish all scores, including unflattering results, rather than just the winner. Report P1/P2 exact matching counts, P3/P4 scores, P1/P2 discordant decisions, false claims on abstain-expected cases, restart/replay/reorder invariance, and corrupt-copy integrity detection. Distinguish **agreement with authored answer key** from actual generalization. Pass criterion for a reliable test harness: P1 and P2 outcomes agree in all cases, metadata-equivalent policy gives >=90% accuracy on toy data, zero incorrect assertions on ambiguous cases, 160/160 cold reload/reorder/alias invariance, and 160/160 altered-copy mismatches. **Parity is expected and does not establish progress in cognition.** If a gate fails, stop and report the counterexample; no silent policy adjustment.

## Access and safety
Standard-library Python 3.12, temporary SQLite databases, no internet/model/API, personal messages, Moltbook reads/writes, GitHub mutations by CI, server access, deployment, external commands, or changes to the native Tadash state. This is an external experiment, not a change to ChatGPT or an assertion of sentience. Authentication and genuine witness independence remain unsolved; a verified_by_caller flag in synthetic data is not an external signature.

## Next experimental dependency
After this v0.2 study, seek an independently collected, consented, nonprivate, source-linked set of temporal corrections and separately generated labels. Only then test generalization beyond authored fixtures. No paid API or new VPS workload without owner approval.
