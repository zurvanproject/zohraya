"""Read-only COOL observation from the Awake/DIOS evidence notebook.

No tick, ingest, pause/resume, service action, external API, or new authority.
The host must supply provenance independently of JSON; local schema validity
does not prove an external sensor origin or establish factual truth.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from . import cool_policy, core

MAX_EVIDENCE = 2000
MAX_RECENT_INGESTS = 256


def _db_readonly(root):
    root = Path(root).expanduser()
    if root.is_symlink():
        raise ValueError("unsafe-awake-root-symlink")
    file = root / "awake.sqlite3"
    if not file.is_file() or file.is_symlink():
        raise ValueError("awake-database-absent-or-symlinked")
    db = sqlite3.connect(file.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def _read_health(db, now):
    control = dict(db.execute("SELECT name,value FROM control"))
    if control.get("schema") != core.SCHEMA or control.get("paused") not in {"0", "1"}:
        raise ValueError("awake-control-invalid")
    n = db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    if n > MAX_EVIDENCE:
        raise ValueError("awake-evidence-capacity-invalid")
    latest = None
    for row in db.execute("SELECT payload FROM evidence"):
        event = json.loads(row["payload"])
        stamp = core.clock(event["observed_at"])
        if latest is None or stamp > latest:
            latest = stamp
    age = None
    if latest is not None:
        delta = (now - latest).total_seconds()
        if delta < 0:
            raise ValueError("future-awake-evidence")
        age = min(int(delta), 365 * 86400)

    recent = now - timedelta(minutes=5)
    total = duplicates = receipts = 0
    for row in db.execute(
        "SELECT at,detail FROM ledger WHERE action='ingest' ORDER BY seq DESC LIMIT ?",
        (MAX_RECENT_INGESTS,),
    ):
        if core.clock(row["at"]) < recent:
            continue
        detail = json.loads(row["detail"])
        a, d = detail.get("added"), detail.get("duplicate")
        if type(a) is not int or type(d) is not int or a < 0 or d < 0:
            raise ValueError("awake-ledger-count-invalid")
        total += a + d
        duplicates += d
        receipts += 1
    return {
        "awake_paused": control["paused"] == "1",
        "evidence_age_seconds": age,
        "duplicate_ratio_5m": duplicates / total if total else None,
        "event_count": n,
        "recent_ingest_receipts": receipts,
    }


def observe(root, *, now=None, trusted_local_source=False,
            resource_sample=None, verified_error_count_5m=None):
    """Operator-facing observation only: never a permission to change state.

    No error count is inferred if it is not explicitly provided by an audited
    host. The absence of such data yields OBSERVE_ONLY, not a fabricated zero.
    """
    if type(trusted_local_source) is not bool:
        raise ValueError("trusted-local-source-not-bool")
    if verified_error_count_5m is not None and (
        type(verified_error_count_5m) is not int
        or not 0 <= verified_error_count_5m <= 1000000
    ):
        raise ValueError("verified-error-count-invalid")
    at = cool_policy.utc(cool_policy.iso(now or datetime.now(timezone.utc)))
    with closing(_db_readonly(root)) as db:
        stats = _read_health(db, at)
    if resource_sample is None:
        try:
            host = cool_policy.host_probe(now=at)
        except (OSError, ValueError):
            # On Windows/unavailable /proc, unknown != healthy.
            host = cool_policy.checked({
                "schema": cool_policy.SCHEMA,
                "sampled_at": cool_policy.iso(at),
                "cpu_load_per_core": None, "ram_used_pct": None,
                "error_burst_5m": None, "duplicate_ratio_5m": None,
                "evidence_age_seconds": None, "awake_paused": None,
            })
    else:
        host = cool_policy.checked(resource_sample)
    if host["sampled_at"] != cool_policy.iso(at):
        raise ValueError("host-sample-time-mismatch")
    sample = {
        **host,
        "awake_paused": stats["awake_paused"],
        "evidence_age_seconds": stats["evidence_age_seconds"],
        "duplicate_ratio_5m": stats["duplicate_ratio_5m"],
        "error_burst_5m": verified_error_count_5m,
    }
    advisory = cool_policy.evaluate(sample, now=at, source_verified=trusted_local_source)
    return {
        "schema": "tadash-awake-cool-readonly/1",
        "mode": advisory["mode"],
        "advisory": advisory,
        "provenance": "local-awake-sqlite-schema-checked-not-external-attestation",
        "missing_metrics": [
            k for k in ("error_burst_5m", "duplicate_ratio_5m", "evidence_age_seconds")
            if sample[k] is None
        ],
        "evidence_count": stats["event_count"],
        "recent_ingest_receipts": stats["recent_ingest_receipts"],
        "awake_paused": stats["awake_paused"],
        "authority": "none",
        "operator_controls_actions": True,
        "execution": "NOT_RUN",
        "database_writes": 0,
        "dios_writes": 0,
        "service_actions": 0,
        "model_calls": 0,
    }
