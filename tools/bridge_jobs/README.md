# Nasuraya remote jobs

Jobs run as the Windows Scheduled Task account. Their source is pinned to a full Git commit SHA and verified against the exact SHA-256 supplied in the GitHub issue command. Only jobs authorized by the server owner should be submitted. Never print keys, passwords, paths, personal information, patient data, or raw logs: issue #149 is public.

Example:
```text
nasu: run <40-character-commit-sha> runtime_probe <64-character-file-sha256>
```

Current first job: runtime_probe.py prints a small, non-sensitive JSON status for validating the expanded bridge.

## One approved Moltbook reply

`moltbook_first_reply.py` is restricted to the existing `nasuraya` account,
post `28bca18b-cba6-443f-b95f-e05aa11e84a2`, and the exact user-approved
public reply from 2026-11-06. It has no registration, new-post, arbitrary-reply,
or private-dialogue API. Run only after a successful v2 runtime probe, using
the immutable commit and file SHA256. Do not queue it on an unverified relay.

The job reuses `moltbook_key.dpapi` under the existing Windows user's local
Moltbook directory. Credentials stay on that host. It checks claim and identity,
reads the complete comment tree before writing, and records a durable `sending`
state before its single POST. A timeout, persistent crash lock, or existing
ledger requires review instead of an automatic repost. An independent GET must
show the exact account, body, ID and verified status before reporting success.
Verification challenges remain local and are not solved automatically.

The installer preserves unique wrapper, prior-agent and task-definition
backups before stopping the existing task; partial writes or missing fresh
authenticated health result restore the previous wrapper and agent. A running
process alone is not evidence that installation succeeded. Windows CI simulates
task operations and network downloads; it does not prove Server 2012 R2 /
PowerShell 4 compatibility or a real VPS install.
