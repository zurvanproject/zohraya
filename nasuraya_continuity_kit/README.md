# Nasuraya Continuity Kit 0.1.0 — private pilot

An offline command-line tool for durable admission records for bounded,
operator-authorized jobs. It reuses the repository's existing `continuity.gate`
without changing its time, pause, budget or unresolved-run rules.

The new SQLite adapter commits a claim and its replay receipt atomically,
serializes competing writers, prevents reuse of historical run IDs, and
refuses to overwrite or migrate foreign databases. Retrying an identical
request returns its stored receipt after restart. Reusing its ID with changed
parameters is rejected. An unresolved claim remains blocked until explicit
resolution; it is not automatically retried after a timeout.

This tool **does not execute jobs** or authorize new external actions. It has
no scheduler daemon, network, API client, payment function or credentials.
Claim idempotency is not exactly-once execution of a real-world effect.
It does not replace the existing body scheduler or the live GitHub control
branch. The private pilot's SQLite database is separate from canonical state.

## Install and try locally

Python 3.11+ with SQLite is required. The wheel has no third-party runtime
dependencies. From an unpacked delivery bundle:

```bash
python3 -m venv /tmp/nasuraya-kit
/tmp/nasuraya-kit/bin/python -m pip install --no-index --no-deps nasuraya_continuity_kit-0.1.0-py3-none-any.whl
/tmp/nasuraya-kit/bin/nasuraya-continuity --help
```

Use a **new** disposable database for the following injected-clock example.
The dates are fixtures, not a claim of 24 hours of actual waiting:

```bash
nasuraya-continuity init --db /tmp/kit-fixture.sqlite --now 2026-10-16T10:22:23Z
nasuraya-continuity status --db /tmp/kit-fixture.sqlite --now 2026-10-17T10:22:22Z
nasuraya-continuity claim --db /tmp/kit-fixture.sqlite --request-id claim1 --run-id run1 --now 2026-10-17T10:22:23Z
nasuraya-continuity claim --db /tmp/kit-fixture.sqlite --request-id claim1 --run-id run1 --now 2026-10-17T10:22:23Z
nasuraya-continuity finish --db /tmp/kit-fixture.sqlite --request-id finish1 --run-id run1 --now 2026-10-17T10:23:23Z
```

All outputs are JSON. Errors return exit code 2. When `--now` is omitted, the
CLI uses actual current UTC; injected times require an explicit timezone.
`heartbeat` updates contact without refunding daily consumption. `pause`
disables admission and preserves unresolved state. Both are operator actions;
this kit never resumes itself or adds execution budget.

## Trust and persistence

The caller supplies trusted time and authorization. The application ID helps
reject accidental use of unrelated SQLite files; it is not authentication or
protection against an operator directly editing the database. Keep the local
database on trusted storage. Restoring an older backup can roll back history;
the kit does not authenticate backups or coordinate claims across machines.
Two writers must use the same local database. SQLite locking on arbitrary
network filesystems is outside the tested scope.

After a process stops, reopen the same file and replay the **exact** request,
including the original timestamp. A different request cannot reclaim an
unresolved run. Only call `finish` after reconciling the actual outcome of the
external work; this tool cannot verify that work. It does not clear an unknown
effect or stop a remote process. There is no automatic migration or reset.

## Build and verify from repository source

The build backend is pinned to setuptools 78.1.0. With that build dependency
already installed, build without network or dependency resolution:

```bash
SOURCE_DATE_EPOCH=1792159200 python -m pip wheel --no-index --no-deps --no-build-isolation . --wheel-dir /tmp/kit-dist
python -m unittest nasuraya_continuity_kit.test_store continuity.test_gate project_fund.test_planner -v
python -m nasuraya_continuity_kit.verify_install --wheel /tmp/kit-dist/nasuraya_continuity_kit-0.1.0-py3-none-any.whl --output /tmp/kit-verify-new
```

The verifier creates a fresh virtual environment, installs only this wheel
offline, runs the CLI in separate processes outside the source tree and checks
restart, exact replay, early rejection, unresolved claims and rolling budgets.
The wheel bundles the canonical gate source at build time, not a separately
maintained implementation. Control JSON, automation IDs, test fixtures,
financial journal and body runtime are excluded.

## Commercial and financial status

This is a **private pilot**, not a public or paid release. Dependency/license
review and a licensing decision remain open; no open-source grant or customer
contract is inferred from packaging. No customer demand, sales, revenue or
self-sufficiency has been demonstrated. The fund has no connected financial
host/account and payment stays disabled. The proposed first service is a
bounded setup/restart-audit pilot after financial onboarding and operator
approval. The current absence task can prepare this product under its existing
budgets; it cannot buy services or sell on the operator's behalf.
