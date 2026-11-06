"""Read-only, fail-closed observation of Tadash unified software-body status.

No native step, actuator, API, or synthetic-to-native reward transfer is permitted.
Source SQLite is backed up from a read-only handle before invoking status on the
copy. This is an observer, not a unified control or training policy.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile

from .engine import connect as connect_ritual, status as ritual_status

SCHEMA = "tadash-ritual-observer/0.1"
NATIVE_SCHEMA = "tadash-unified-receipt-cycle/1"
EXPECTED_COUNTERS = ("experience", "workspace", "motivation", "autonomic", "neurovisceral", "native")


def _digest(report: dict) -> str:
    encoded = json.dumps(report, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_native_status(report: dict) -> dict:
    """Require coherent, source-pinned native receipts; reject unknown versions."""
    if not isinstance(report, dict) or report.get("schema") != NATIVE_SCHEMA:
        raise ValueError("unrecognized native status schema")
    required_true = ("ready", "synchronized", "recent_receipts_agree",
                     "initial_source_pinned", "all_experience_flags_enabled",
                     "software_only")
    if any(report.get(key) is not True for key in required_true):
        raise ValueError("native readiness, receipt agreement, or origin pin failed")
    if report.get("physical_actuation") is not False or report.get("api_calls") != 0:
        raise ValueError("native status is not strictly offline software-only")
    if report.get("pending_intents") != []:
        raise ValueError("unresolved native intents; refusing status ingestion")
    n = report.get("completed_cycles")
    if type(n) is not int or n < 0:
        raise ValueError("invalid completed cycle count")
    counts = report.get("counters")
    if not isinstance(counts, dict) or any(type(counts.get(k)) is not int or counts[k] != n
                                           for k in EXPECTED_COUNTERS):
        raise ValueError("divergent native and cognitive receipt counts")
    source = report.get("last_receipt_source")
    if n and (not isinstance(source, str) or not source.strip() or len(source) > 4096):
        raise ValueError("no trusted source for last native receipt")
    if not n and source is not None:
        raise ValueError("source with zero completed cycles")
    return {"completed_cycles": n, "last_receipt_source": source,
            "source_pinned": True, "receipt_counters_agree": True,
            "physical_actuation": False}


def observe_native(body_root: Path, body_session: Path, timeout: int = 60) -> dict:
    """Inspect only a fresh SQLite snapshot; never execute on the live ledger."""
    body_root = Path(body_root).resolve(strict=True)
    body_session = Path(body_session)
    if not body_root.is_dir() or not (body_root / "examples/nasuraya_body_loop/__main__.py").is_file():
        raise ValueError("verified BodyLoop checkout not found")
    if body_session.is_symlink():
        raise ValueError("native session symlinks are prohibited")
    native = body_session.resolve(strict=True)
    info = native.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("native session must be an owned regular SQLite file")
    with tempfile.TemporaryDirectory(prefix="tadash-status-snapshot-") as folder:
        snapshot = Path(folder) / "body.sqlite"
        # SQLite online backup captures the WAL-consistent snapshot without writing
        # to the user's live source database.
        with sqlite3.connect(native.as_uri() + "?mode=ro", uri=True, timeout=5) as origin:
            with sqlite3.connect(snapshot) as destination:
                origin.backup(destination)
        snapshot.chmod(0o600)
        command = [sys.executable, "-m", "examples.nasuraya_body_loop",
                   "unified-status", "--session", str(snapshot)]
        environment = {k: v for k, v in os.environ.items()
                       if not (k.endswith("_API_KEY") or k.endswith("_TOKEN")
                               or k in ("OPENAI_API_KEY", "GITHUB_TOKEN"))}
        completed = subprocess.run(command, cwd=body_root, env=environment,
                                   stdin=subprocess.DEVNULL, capture_output=True,
                                   text=True, timeout=timeout, check=False)
        if completed.returncode != 0:
            raise ValueError("native unified-status failed on immutable snapshot")
        try:
            report = json.loads(completed.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError, TypeError) as exc:
            raise ValueError("native unified-status returned no valid JSON") from exc
        return validate_native_status(report)


def _open_ledger(db: Path) -> sqlite3.Connection:
    db = Path(db).expanduser()
    if db.is_symlink():
        raise ValueError("bridge ledger symlinks are prohibited")
    db.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(db, timeout=5)
    db.chmod(0o600)
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("""CREATE TABLE IF NOT EXISTS native_status_snapshots (
      id INTEGER PRIMARY KEY, seen_utc TEXT NOT NULL, completed_cycles INTEGER NOT NULL,
      last_receipt_source TEXT, status_sha256 TEXT NOT NULL UNIQUE
    )""")
    connection.commit()
    return connection


def append_checkpoint(ledger: sqlite3.Connection, native: dict) -> bool:
    """Idempotent monotone status history. This does NOT count as a new body action."""
    n = native["completed_cycles"]
    source = native["last_receipt_source"]
    seal = _digest({"schema": NATIVE_SCHEMA, "count": n, "source": source})
    ledger.execute("BEGIN IMMEDIATE")
    try:
        previous = ledger.execute(
            "SELECT completed_cycles,last_receipt_source FROM native_status_snapshots "
            "ORDER BY id DESC LIMIT 1").fetchone()
        if previous is not None:
            last_n, last_source = previous
            if n < last_n or (n == last_n and source != last_source):
                raise ValueError("native receipt count regressed or source changed without cycle")
        cursor = ledger.execute(
            "INSERT OR IGNORE INTO native_status_snapshots"
            "(seen_utc,completed_cycles,last_receipt_source,status_sha256) VALUES(?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), n, source, seal))
        ledger.commit()
        return cursor.rowcount == 1
    except BaseException:
        ledger.rollback()
        raise


def run_once(ritual_db: Path, bridge_db: Path,
             body_root: Path | None, body_session: Path | None) -> dict:
    """One finite poll. Never dispatches commands or trains from native feedback."""
    output = {"schema": SCHEMA, "kind": "read_only_observation",
              "ritual": "waiting_for_initialization", "native": "not_configured",
              "physical_actuation": False, "api_calls": 0,
              "synthetic_to_native_training": False}
    ritual_db = Path(ritual_db).expanduser()
    if ritual_db.is_file() and not ritual_db.is_symlink():
        # Independent ritual state remains a synthetic exercise.
        with sqlite3.connect(ritual_db.as_uri() + "?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            summary = ritual_status(connection)
        output["ritual"] = {"synthetic_episodes": summary["episodes"],
                            "synthetic_holdout": summary["holdout"]["correct"],
                            "synthetic_holdout_total": summary["holdout"]["total"]}
    if (body_root is None) != (body_session is None):
        raise ValueError("body_root and body_session must be supplied together")
    if body_root is not None:
        if not Path(body_session).is_file():
            output["native"] = "waiting_for_session"
        else:
            native = observe_native(Path(body_root), Path(body_session))
            with _open_ledger(Path(bridge_db)) as ledger:
                recorded = append_checkpoint(ledger, native)
            output["native"] = dict(native, new_checkpoint_recorded=recorded)
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only ritual/native observer; no body control")
    parser.add_argument("--ritual-db", type=Path, required=True)
    parser.add_argument("--bridge-db", type=Path, required=True)
    parser.add_argument("--body-root", type=Path)
    parser.add_argument("--body-session", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run_once(args.ritual_db, args.bridge_db, args.body_root, args.body_session)
    except (ValueError, sqlite3.Error, OSError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"schema": SCHEMA, "status": "rejected",
                          "reason": str(error), "native_actions": 0}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
