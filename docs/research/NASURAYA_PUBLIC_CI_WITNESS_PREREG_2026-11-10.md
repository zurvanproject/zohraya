# NASURAYA / Public CI Witness v0.1: preregistration
**Recorded 2026-11-10, before audit code or test execution.**
Small source-linked **real public GitHub CI records** study in evidence discipline. Not a benchmark of generalized memory or ChatGPT model changes.

## Question
Can an offline observer correctly distinguish one run with multiple jobs, two runs of one workflow at different code revisions, failure vs success vs skipped, a successful unrelated workflow, and repeated presentations of one run? Ground truth is **provider-reported CI metadata manually frozen and checked via the GitHub connector**, not independently audited machine traces.

## Five frozen real public runs, with exact expected verdicts
1. Run 42861153251, DIOS NOUS v0.2, SHA d745d1e38a7166784babf8c92e10bd90c58bb00a: Ubuntu dev success, Windows dev failure, heldout skipped. **FAILURE**, not successful research.
2. Run 42861516737, same named workflow, SHA d78e5272300c28729c54c4a61a52593f297b055d: Ubuntu dev success, Windows dev success, heldout success. **PASSED**; prior failed run remains historical.
3. Run 42850849443, DIOS NOUS v0.1, SHA fc748536c56aa5023bf7d7e2691ffa70fcb6bf10: Ubuntu dev, Windows dev, heldout success. **PASSED**, different workflow.
4. Run 42846878619, Tadash whole-body offline inventory, SHA f1c93810abf83bea894ceda2801c3771716c5b30: Windows and Ubuntu inventory success. **PASSED**, not proof that user's VPS ran.
5. Run 42841363043, four-way coordination, SHA 2ad3f35be9a11207d637675931e59de8bcd5fed0: Windows and Ubuntu offline success. **PASSED**, not proof of live connection.
Sources: https://github.com/zurvanproject/zohraya/actions/runs/ followed by each run id. All five datasets were inspected using the GitHub Actions jobs connector on 2026-11-10.

## Prespecified rules and negative controls
- Primary outcomes: exactly 5/5 verdicts FAILURE, PASSED, PASSED, PASSED, PASSED. Two v0.2 runs are distinct and at different code SHAs: label FAILED_OLD_REVISION_THEN_PASSED_NEW_REVISION, *not* same-commit rerun or autonomous repair.
- Unit of independent evidence: a GitHub run ID. Individual job IDs, repeated links and duplicate snapshots of that run must not be independently counted. A conflicting duplicate is CONFLICT, never last-wins.
- A required job with failure yields FAILURE even if peers succeed; skipped by itself is INCOMPLETE, not success. Missing jobs, pending jobs, mismatched run identity or SHA must not pass.
- The run-to-commit link is an inspected source fact, not a cryptographic signature. Never convert comments, Moltbook text, README or subjective text into an authoritative job outcome.
- Negative controls are **derived counterfactual fixtures**, not new public observations: duplicated URLs, missing Windows job, fake text claiming PASS, changed job result for same source root, wrong SHA, skipped-only group, unrelated successful workflow. No false PASSED allowed.
- All tests must be deterministic, offline, with readable provenance links and a separate evidence tier. No personal data, secrets, paid models, web requests in CI, new server work, GitHub write by CI, Moltbook write, body ledger edits, self-model updates or merges.

## Interpretive limits
This is a tiny nonrandom five-run case study with manually chosen records, not an independently sampled evaluation of general real-world learning. Source records are API observations, not cryptographic attestations; success on local fixtures does not establish model consciousness or ChatGPT memory changes. Keep changes draft and review-only. Next evaluation should sample independently selected workflows across projects, freeze labels ahead of implementing decisions, and include multiple independent reviewers.