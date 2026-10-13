# Tadash reflection runtime 0.2

This extends the recovered 0.1 implementation in the same `tadash_body` layout.
SQLite decision schema remains 0.1 for compatibility; runtime behavior is 0.2.
This changes external project software and saved evidence, not model weights.

## Behavior

- A derived indexed feedback table retrieves relevant action contracts throughout
  the ledger, rather than examining only the last 128 same-topic decisions.
- Action signatures include the expected outcome and normalize order-insensitive
  claims/requirements. Action IDs, source context and topic still match exactly.
- The latest verified feedback must have an unexpired observed witness when an
  expiry was supplied. An expired newer correction cannot silently revive an
  older preference. Unverified corrections do not displace verified feedback.
- The penalty remains 0.6. No calibrated probabilities or semantic transfer
  mechanism were introduced.
- Opening a copied 0.1 ledger builds the derived index transactionally without
  rewriting original decision records. Identical old requests return their
  originally recorded plans/receipts, including the original engine fingerprint.
  A different request ID is required for a fresh decision under the new runtime.
- Running unresolved effects require explicit reconciliation. Reconciliation of
  a side effect does not automatically reconstruct an unsaved body checkpoint.

## Reproduce

From this directory:

```sh
python3 run_tests.py --reflection --output /tmp/tadash-v02-tests
python3 run_stage2_evaluation.py --output /tmp/tadash-v02-comparison.json
python3 run_stage2_durability.py --output /tmp/tadash-v02-durability --old-root ../baseline_v01/tadash_body
```

Use a new output directory for durability checks. The archive includes the exact
0.1 baseline and frozen stage2 cases. Do not rerun the fixture generator and
replace the frozen evaluation files. Source artifact hashes are retained.

99 unit tests passed: 89 integrated tests including 8 added regressions, plus
10 original DecisionCore tests. Existing ten cognitive cases and twelve body
scenarios also passed. The optional endurance/special suites were not rerun.

The 26 new cases were frozen before editing runtime code. Six development cases
and twenty final comparison cases are reported separately. The same assistant
authored the reference rules, fixtures and runtime, and inspected the baseline
results before changes. This is an exposed, constructed contract evaluation;
it is not independent or blinded. There is no statistical generalization claim.

Final20: core 10, evidence gates 16, old memory16, revised memory20. The four
revised-memory improvements address aged feedback, expected-outcome scope,
expired evidence and requirement order. Development6: old memory2, revised6.

## Durable verification

Twenty dedicated checks passed. Capacity data was explicitly bulk-generated
from an engine-completed fixture template; it is not 10,000 callback executions
or a long-running workload benchmark. The final ledger has 10,000 records,
retains the earliest correction and commitment, rejects overflow without
deletion, and survives a cold-process backup restore. Backup size:46,960,640bytes.

Separate tests terminate real subprocesses before planning commit, during
completion after an observable callback effect, and after completed commit.
They check rollback of feedback/runtime together, replay protection, explicit
reconciliation and old-version index migration. Sequential operation only.

Earlier fixture seeding was interrupted while incomplete. Attempting to reopen
that test directory encountered a locked database. It was not counted as a
successful test. The final capacity test used a fresh isolated directory and
an explicit bulk-construction method. Its raw results are included.

## Continue actual commitments

`evidence/continuation/resume_checkpoint.sqlite` is a copied continuation of the
prior task ledger. The original ledger bytes are unchanged. A new retrospective
record of the actual A053L image inspection selected `inspect_source` using the
previous correction. Cold-process recall repeated the selection.

The record describes assistant visual inspection already performed, not a
software OCR executor or independently demonstrated OCR accuracy improvement.

Book:7132 whitespace tokens of authored prose (including titles/locators),
42868 still required for50000. All254 source reading units are catalogued and
their viewer images decoded. Three new selected short fragments were recorded.
Full word-by-word collation, complete names/index and all-grid verification
remain open. The old100-page working edition is not a finished50000-word edition.

The book viewer and authored supplement preserve the separation of observed,
interpreted, unresolved and creative content. Further authored writing is
authorized and remains unfinished; manuscript ambiguity does not itself prevent
that writing. Missing printed30/31 and unresolved compressed name/formula
strings limit verified historical reconstruction with the supplied material.

Book pavilion structure reported in the separate conversation is not merged
or claimed as connected by this package. A future adapter should link its source,
exercise and creation records to this decision ledger using explicit contracts.

## Remaining boundaries

Input truth and verification are caller declarations. Expiry is optional;
unmarked staleness is not inferred. Exact context/topic/action matching does not
understand paraphrases. Capacity remains10,000 decisions and requires an explicit
future storage policy to expand. Authenticating producers, concurrency and
physical actuators remain outside the verified scope.
