# ATMOSPHERE: «هفت اختر» security follow-up (2026-11-17)

**Research record only / فقط ثبت پژوهشی.** This folder records the isolated audit of PR #257 stacked on PR #246. The proposed security patch has **not** been applied to runtime modules, main, PR #257, or any VPS. This draft PR is not deployable.

## Source & provenance

- Source PR #257 head: `c840eab667a2932b84ea11e19fe32e18f2438fb4` (Draft)
- Underlying PR #246 head: `2116cead386f7d4983cc51e83298f68111103d27` (Draft)
- Original unpatched GitHub Actions run: https://github.com/zurvanproject/zohraya/actions/runs/43969273570 , **101/101** passing incl. **14/14** seven-stars.
- Isolated local probes reported **6/6**; proposed patch regression tests **5/5** in a Linux sandbox with disposable Ed25519 keys and SQLite. Not an operational Ubuntu reboot or power-cut test.
- `REPORT_FA.md`: full Persian audit, observed behaviours, threat model, caveats, rollback and outstanding controls. The report predates this GitHub archival commit; its statement that no branch/PR was changed describes the *original audit execution*.
- `hardening.patch`: **proposal, not applied**. Addresses multi-root verification/revocation policy, explicit second approval before delivery, and atomic directory publishing.
- `test_atmosphere_security_regression.py`: a review copy of the new regression test introduced by the patch. It is **not runnable against unpatched code**.

## Test on a disposable clone only

From repo root at the specified PR #257 commit, after review:

```bash
git apply --check research/atmosphere-seven-stars-followup-20261117/hardening.patch
git apply research/atmosphere-seven-stars-followup-20261117/hardening.patch
PYTHONPATH=tools python -m unittest discover -s tests -p 'test_atmosphere_security_regression.py' -v
```

**Do not merge or deploy this patch as-is.** The proposal intentionally changes existing `root=PinnedRoot` callers to `TrustedRoots` and requires out-of-band approved manifest fingerprints at delivery. Existing CI tests/callers need migration and the full original test suite has **not** passed with this patch. Off-host trust policy and two-person approval are not provisioned by these files. `os.fork` crash tests are Linux-only and need an isolated test runner.

## Scope, risk and rollback

Only research documentation and candidate code have been recorded here. No modifications of executable `tools/` files are present in this draft PR. Do not run the fault-injection tests against operational databases.

Before merging any hardening: review API migration, define secure key revocation/quarantine and manual approval, test the full suite and actual Ubuntu restart/backup recovery independently. If the patch is applied to a disposable clone, `git apply -R research/atmosphere-seven-stars-followup-20261117/hardening.patch` reverts it. To undo this research record, close the Draft PR and delete/revert the isolated research branch; this does not affect original PRs. On production, rollback must keep evidence ingress disabled rather than silently restoring the older weaker validation path.

All secrets in these tests are synthetic/ephemeral; no real signer key or production data included.
