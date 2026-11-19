# Fourway Evidence Gate v0.2 | preregistered integration contract

**Registered 2026-11-10 before implementation and the integration test.** This is a companion to the already-reviewed public CI witness in PR #183 and read-only fourway observer in PR #178. Whole-body development remains the VPS mission in Issue #180. No further VPS job is authorized.

## Observed inputs and frozen expected answer
Source A: the five public GitHub Actions runs frozen in `docs/evidence/public-ci-witness-v01/frozen-public-github-runs.json`, previously inspected by the connected GitHub app. The body-atlas CI run 42846878619 and fourway CI run 42841363043 both passed. **A green GitHub Actions job proves neither VPS execution nor current Moltbook activity.**

Source B: exact owner-account messages in Issue #149 observed on 10 November 2026:
- 6771977584: exact SHA-pinned request `nasu_wholebody_phase1`; no matching Bridge v2 reply
- 6770326192: SHA-pinned fresh request `nasu_research_status`; no matching reply
- 6740249936 / 6740270749: an *older* request/reply with `STATE=RUNNING`; historical, not current health
- 6724967463 / 6724974483: an *older* `moltbook_repair_retest` request/reply with `REPAIR=REPLAY` and `GET=0`; local retrospective evidence, not a fresh Moltbook GET.

Expected report: CI body-atlas and fourway checks both PASSED; live whole-body atlas `QUEUED_NO_RECEIPT`; latest 24h worker status `STATUS_REQUEST_PENDING`; prior status historical `RUNNING`; Moltbook `HISTORICAL_REPLAY_ONLY`; whole fourway `NOT_LIVE_VERIFIED`. No confidence inflation, no claim of complete physical body or independent AI.

## Precommitted negative controls
1. Fake (nonowner) Bridge success must not promote a status.
2. Owner-account reply for wrong request ID or wrong job name must not promote it.
3. Multiple conflicting claimed results for the same request must produce `CONFLICT` and no successful execution claim.
4. New correct Bridge receipt may promote atlas only to `REPORTED_INVENTORY`, never `PHYSICAL_BODY_COMPLETED`.
5. Explicit failure, timeout and `OK FAIL=...` must be reported as failure.
6. Partial GitHub comment pagination/read failure must not be treated as an empty or healthy queue.
7. One historical Moltbook replay with `GET=0` must not be treated as new Moltbook activity.
8. A green body-atlas CI run alone cannot be used to promote the Atlas VPS status.
9. API comment text and posted GitHub owner identity are not hardware attestation, identity-proof of a particular process, or a mandate to issue commands.

## Test and operating model
Use Python 3.12 stdlib. `--from-file` combines the frozen public CI receipt set and a minimum verified subset of actual Bridge comments. `--live` may only perform bounded, TLS-verified GET requests against the fixed GitHub API path for Issue #149, with no token, write, remote command, server install, paid model call, Moltbook POST or memory/model edit. Outputs are status-only JSON and links. CI tests offline on Windows and Ubuntu with no production credentials. Expected first-run: statuses above and clean fail-closed behavior for derived negative controls. No hidden holdout is claimed; this is a focused integration contract using a hand-selected public example, not an independent statistical benchmark.

Acceptance: at least 10 focused tests, exact registered report for the frozen evidence, strict distinction CI success vs server receipt, and no false positive on negative controls. Keep Draft for review; do not merge or deploy automatically.
