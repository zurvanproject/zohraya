# Nasuraya Continuity Kit 0.2.0 — private pilot

An offline command-line tool for durable admission records for bounded,
operator-authorized jobs. It reuses the repository's existing `continuity.gate`
without changing its time, pause, budget or unresolved-run rules.

The new SQLite adapter commits a claim and its replay receipt atomically,
serializes competing writers, prevents reuse of historical run IDs, and
refuses to overwrite or migrate foreign databases. Retrying an identical
request returns its stored receipt after restart. Reusing its ID with changed
parameters is rejected. An unresolved claim remains blocked until explicit
resolution; it is not automatically retried after a timeout.

Version 0.2 adds **one executed local job**: a bounded deterministic integrity
report published only in this same SQLite database. It has no general job
callbacks, scheduler daemon, network, API client, payments or credentials.
Claim idempotency is not exactly-once execution of a real-world effect.
It does not replace the existing body scheduler or the live GitHub control
branch. The private pilot's SQLite database is separate from canonical state.

## Install and try locally

Python 3.11+ with SQLite is required. The wheel has no third-party runtime
dependencies. From an unpacked delivery bundle:

```bash
python3 -m venv /tmp/nasuraya-kit
/tmp/nasuraya-kit/bin/python -m pip install --no-index --no-deps nasuraya_continuity_kit-0.2.0-py3-none-any.whl
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

`status` reads control, request count and run count from one SQLite statement,
so a concurrent commit cannot mix an old admission decision with newer counts.
It observes a snapshot, not a lock or permission to execute a future job. Existing
caller transactions remain owned by the caller; status neither commits nor rolls
them back. Other commands still enforce admission independently.

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
python -m unittest nasuraya_continuity_kit.test_local_job nasuraya_continuity_kit.test_store continuity.test_gate project_fund.test_planner -v
python -m nasuraya_continuity_kit.verify_install --wheel /tmp/kit-dist/nasuraya_continuity_kit-0.2.0-py3-none-any.whl --output /tmp/kit-verify-new
```

The verifier creates a fresh virtual environment, installs only this wheel
offline, runs the CLI in separate processes outside the source tree and checks
restart, exact replay, early rejection, unresolved claims and rolling budgets.
The wheel bundles the canonical gate source at build time, not a separately
maintained implementation. Control JSON, automation IDs, test fixtures,
financial journal and body runtime are excluded.

## Execute a bounded local job (0.2)

`run-local` is an explicit one-shot invocation on the trusted host. It does not
start itself during an outage. The existing enabled/24-hour/daily/unresolved gate
remains authoritative. The CLI uses actual UTC by default; the following times
are **injected fixtures**, for a new disposable database, not elapsed waiting:

```bash
printf '["abc", "", "سلام"]' > /tmp/integrity-input.json
nasuraya-continuity init --db /tmp/local-job.sqlite --now 2026-10-16T10:22:23Z
nasuraya-continuity run-local --db /tmp/local-job.sqlite --request-id request1 --run-id run1 --now 2026-10-17T10:22:23Z --input /tmp/integrity-input.json
nasuraya-continuity inspect-local --db /tmp/local-job.sqlite --run-id run1
```

The input must be a regular local file: at most 65,536 bytes containing a JSON
list of at most 256 strings, each at most 256 Unicode characters with valid
UTF-8 encoding. This bounds both stored input and computation. No output path or
command is accepted. The report contains SHA-256 of the exact input bytes, each
string in order, record count and byte counts. It measures integrity fingerprints;
it does not assert authenticity or compare against an external trusted manifest.

Claim, input snapshot, request binding and `running` job commit atomically using
the existing admission/receipt adapter. The winning invocation computes a report.
Report publication, `completed` and the existing `finish` receipt commit atomically
in the same database. Input is retained so a separate reader can verify the result.
The optional job table is additive; no canonical body/control state is imported.

Internal finish receipts use an available ID selected inside that same write
transaction. Caller IDs remain unrestricted by a reserved prefix. If an older
receipt already uses the preferred ID, deterministic numbered alternatives are
checked without altering that receipt or repeating computation. This also covers
a competing heartbeat committed while the report was being computed. The public
run/request binding, database schema and completed replay response stay unchanged.

Repeat the **exact run-local command**, including timestamp and file bytes, to
retrieve a completed or abandoned record without computing the report again.
Changing any bound parameter fails. A legacy `claim` receipt cannot be upgraded
into execution authority. Competing identical requests have only one executing
invocation. This guarantee concerns report publication in one local SQLite file;
it is not a guarantee for arbitrary effects, backup rollback or cross-host workers.

### Process termination and host review

- Before claim transaction commits: no admitted work or budget consumption.
- After claim, including after computation but before result commit: `running`
  means unresolved, even if computation might have finished. Exact retries and
  new work stay blocked indefinitely. The generic `finish` command refuses it.
- After result/finish commit, including before stdout is delivered: cold replay
  returns the stored report and does not execute again.

After inspecting the database and confirming the worker has stopped, the host
can explicitly abandon an unresolved run. The following is a host attestation,
not automatic process discovery or authentication:

```bash
nasuraya-continuity abandon-local --db /tmp/local-job.sqlite --request-id review1 --run-id run1 --operator host-name --evidence 'PID was stopped and reaped; no result committed' --worker-stopped
```

Abandonment retains input, history and the review note, stores **no successful
result**, never reruns the task and never refunds the rolling daily allowance.
A late worker cannot publish after abandonment. A new job needs a new ID and a
fresh gate admission. All writers must use this upgraded adapter; an old binary
or direct SQL can bypass application-level guards under the trusted-host model.

### Operator contact during computation

Pause prevents new admissions; it is not process termination. An already claimed
local report may commit while preserving the pause/contact recorded by another
connection. A completed replay returns historical result data, never restores its
old control state or grants new execution authority. If contact advances beyond
the worker's supplied finish timestamp, the unchanged gate rejects that stale
finish: result publication rolls back and the claim stays unresolved for explicit
host review. Do not automatically clear it or replay computation.

The operator-race regressions use event barriers and separate SQLite connections,
not timing sleeps. They check colliding pause/heartbeat receipt IDs, preservation
after reopen, stale-finish rollback and replay with computation forbidden. These
are injected-clock local contracts, not proof of real-world exactly-once effects.

### Independent offline/crash verification

On Linux with `libseccomp.so.2` installed (a **verifier-only** prerequisite):

```bash
python -m nasuraya_continuity_kit.verify_local_job --wheel /tmp/kit-dist/nasuraya_continuity_kit-0.2.0-py3-none-any.whl --output /tmp/local-job-verify-new
```

The verifier denies network syscalls in the kernel, checks EPERM in parent and
child, installs the wheel with `--no-index --no-deps` into a fresh virtualenv,
then invokes the installed CLI outside the source checkout. Four workers are
actually killed with SIGKILL: after claim, after computation, during the result
transaction and after commit. Replays run with report computation forbidden.
An independent SQLite/hash reader checks stored inputs, reports and receipts.
Injected fault hooks are verification code only; the CLI has no crash switches.
This verifies offline computation without pulling an internet cable or simulating
a multi-day outage. There is no persistent background execution after this demo.

## Commercial and financial status

This is a **private pilot**, not a public or paid release. Dependency/license
review and a licensing decision remain open; no open-source grant or customer
contract is inferred from packaging. No customer demand, sales, revenue or
self-sufficiency has been demonstrated. The fund has no connected financial
host/account and payment stays disabled. The proposed first service is a
bounded setup/restart-audit pilot after financial onboarding and operator
approval. The current absence task can prepare this product under its existing
budgets; it cannot buy services or sell on the operator's behalf.
