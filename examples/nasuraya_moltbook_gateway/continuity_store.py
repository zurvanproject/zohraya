"""Opt-in, local, quarantined SQLite history of public social observations.

This is NOT Tadash's private/autobiographical memory or a learning input.
Only the bounded, validated read-only observation adapter can supply data.
No network, model API, task scheduler, native body, or publication is imported.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile

from runtimes.tadash_body.social_observations import load_social_observations

SCHEMA = "nasuraya-public-continuity/1"
OBSERVATION_SCHEMA = "tadash-social-observations/1"
TRUST = "untrusted_external"


class ContinuityError(ValueError):
    """A fail-closed local persistence or provenance error."""


def _digest(doc: object) -> str:
    raw = json.dumps(doc, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _private_dir(parent: Path) -> None:
    if parent.is_symlink() or not parent.is_dir():
        raise ContinuityError("private state directory must already exist and not be a link")
    if os.name == "posix":
        mode = parent.stat().st_mode
        if (stat.S_IMODE(mode) & 0o077) != 0:
            raise ContinuityError("state directory must deny group/other access")


def _check_db_path(db: Path, *, create: bool) -> Path:
    _private_dir(db.parent)
    if db.is_symlink():
        raise ContinuityError("refusing symlinked SQLite database")
    if db.exists():
        mode = db.stat().st_mode
        if not stat.S_ISREG(mode):
            raise ContinuityError("SQLite path must be a regular file")
        if os.name == "posix" and (stat.S_IMODE(mode) & 0o077):
            raise ContinuityError("SQLite file must deny group/other access")
    elif create:
        try:
            fd = os.open(str(db), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise ContinuityError("SQLite path changed unexpectedly") from exc
        else:
            os.close(fd)
    else:
        raise ContinuityError("SQLite history not yet created")
    return db


def _open(db: Path, *, create: bool = False) -> sqlite3.Connection:
    _check_db_path(db, create=create)
    if create:
        conn = sqlite3.connect(str(db), timeout=5, isolation_level=None)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
    else:
        # Read-only means status/backup cannot silently create or modify an archive.
        conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True,
                               timeout=5, isolation_level=None)
        conn.execute("PRAGMA query_only=ON")
    return conn


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS continuity_meta (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS continuity_runs (
            receipt_sha256 TEXT PRIMARY KEY,
            observed_utc TEXT NOT NULL,
            imported_utc TEXT NOT NULL,
            item_count INTEGER NOT NULL CHECK(item_count BETWEEN 0 AND 20)
        );
        CREATE TABLE IF NOT EXISTS continuity_items (
            source_id TEXT NOT NULL,
            version_sha256 TEXT NOT NULL,
            author_untrusted TEXT NOT NULL,
            title_untrusted TEXT NOT NULL,
            excerpt_untrusted TEXT NOT NULL,
            trust TEXT NOT NULL CHECK(trust = 'untrusted_external'),
            first_observed_utc TEXT NOT NULL,
            PRIMARY KEY(source_id, version_sha256)
        );
        CREATE TABLE IF NOT EXISTS continuity_membership (
            receipt_sha256 TEXT NOT NULL REFERENCES continuity_runs(receipt_sha256),
            source_id TEXT NOT NULL,
            version_sha256 TEXT NOT NULL,
            PRIMARY KEY(receipt_sha256, source_id),
            FOREIGN KEY(source_id, version_sha256)
                REFERENCES continuity_items(source_id, version_sha256)
        );
    """)
    conn.execute("INSERT OR IGNORE INTO continuity_meta VALUES('schema', ?)", (SCHEMA,))
    row = conn.execute("SELECT value FROM continuity_meta WHERE key='schema'").fetchone()
    if row is None or row[0] != SCHEMA:
        raise ContinuityError("incompatible continuity schema")


def ingest(snapshot: str | Path, db: str | Path) -> dict:
    """Idempotently archive a *fresh* quarantined snapshot, never train from it."""
    snapshot, db = Path(snapshot), Path(db)
    # The existing bridge protects this folder with user/SYSTEM-only ACLs on
    # Windows. Keep the new history in the exact same private directory.
    if snapshot.parent.resolve() != db.parent.resolve():
        raise ContinuityError("snapshot and history must share the private state directory")
    _private_dir(db.parent)
    observation = load_social_observations(snapshot)
    if (observation.get("schema") != OBSERVATION_SCHEMA
            or observation.get("origin") != "moltbook_public_feed"
            or observation.get("permitted_use") != "human_reviewed_research_only"
            or observation.get("may_instruct_agent") is not False
            or observation.get("may_modify_body") is not False
            or observation.get("may_publish") is not False):
        raise ContinuityError("observation boundary does not permit import")
    items = observation["items"]
    if any(row.get("trust") != TRUST for row in items):
        raise ContinuityError("unexpected trust level")
    observed_utc = observation["observed_utc"]
    receipt = _digest({"schema": SCHEMA, "observed_utc": observed_utc,
                       "items": sorted(items, key=lambda item: item["source_id"])})
    with closing(_open(db, create=True)) as conn:
        _schema(conn)
        # executescript above commits its own schema setup; all episode writes
        # still occur in one SQLite transaction.
        conn.execute("BEGIN IMMEDIATE")
        try:
            previous = conn.execute(
                "SELECT 1 FROM continuity_runs WHERE receipt_sha256=?", (receipt,)
            ).fetchone()
            if previous:
                conn.commit()
                return {"schema": SCHEMA, "replayed": True,
                        "new_item_versions": 0, "items_in_snapshot": len(items),
                        "receipt_sha256": receipt, "trust": TRUST,
                        "may_train": False, "may_modify_body": False,
                        "may_publish": False}
            imported_utc = datetime.now(timezone.utc).isoformat()
            conn.execute("INSERT INTO continuity_runs VALUES(?,?,?,?)",
                         (receipt, observed_utc, imported_utc, len(items)))
            inserted = 0
            for row in items:
                version = _digest({k: row[k] for k in (
                    "source_id", "author_untrusted", "title_untrusted",
                    "excerpt_untrusted", "trust")})
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO continuity_items VALUES(?,?,?,?,?,?,?)",
                    (row["source_id"], version, row["author_untrusted"],
                     row["title_untrusted"], row["excerpt_untrusted"],
                     TRUST, observed_utc))
                inserted += cursor.rowcount
                conn.execute("INSERT INTO continuity_membership VALUES(?,?,?)",
                             (receipt, row["source_id"], version))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return {"schema": SCHEMA, "replayed": False,
            "new_item_versions": inserted, "items_in_snapshot": len(items),
            "receipt_sha256": receipt, "trust": TRUST,
            "may_train": False, "may_modify_body": False,
            "may_publish": False}


def status(db: str | Path) -> dict:
    """Metadata only; does not reveal raw social text or create files."""
    with closing(_open(Path(db))) as conn:
        row = conn.execute("SELECT value FROM continuity_meta WHERE key='schema'").fetchone()
        if row is None or row[0] != SCHEMA:
            raise ContinuityError("unknown continuity schema")
        count, last = conn.execute(
            "SELECT count(*), max(observed_utc) FROM continuity_runs").fetchone()
        unique_ids, versions = conn.execute(
            "SELECT count(DISTINCT source_id), count(*) FROM continuity_items").fetchone()
    return {"schema": SCHEMA, "imports": count, "unique_ids": unique_ids,
            "item_versions": versions, "latest_observed_utc": last,
            "trust": TRUST, "may_train": False, "may_modify_body": False,
            "may_publish": False}


def backup(db: str | Path, dest: str | Path) -> dict:
    """Consistent portable SQLite backup in the existing private directory.

    The .sqlite file can be safely transferred later via an encrypted channel.
    Reject overwrites and public destination directories.
    """
    db, dest = Path(db), Path(dest)
    if db.resolve() == dest.resolve() or db.parent.resolve() != dest.parent.resolve():
        raise ContinuityError("backup must be a new file in the same private directory")
    _private_dir(dest.parent)
    if dest.exists() or dest.is_symlink():
        raise ContinuityError("backup destination already exists")
    fd, temp_path = tempfile.mkstemp(prefix=".nasuraya-backup-", suffix=".sqlite",
                                     dir=str(dest.parent))
    os.close(fd)
    try:
        with closing(_open(db)) as source:
            with closing(sqlite3.connect(temp_path)) as target:
                source.backup(target)
        # Recheck before publishing; the private directory prevents adversarial
        # replacement by other unprivileged users.
        if dest.exists() or dest.is_symlink():
            raise ContinuityError("backup destination changed")
        os.replace(temp_path, dest)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return {"ok": True, "path": str(dest),
            "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
            "scope": "quarantined_public_only", "encrypted": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quarantined, local public-observation archive")
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("ingest", help="Import a fresh snapshot once")
    imp.add_argument("--snapshot", type=Path, required=True)
    imp.add_argument("--db", type=Path, required=True)
    show = sub.add_parser("status", help="Read private archive metadata")
    show.add_argument("--db", type=Path, required=True)
    bk = sub.add_parser("backup", help="Create an unencrypted portable SQLite backup")
    bk.add_argument("--db", type=Path, required=True)
    bk.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "ingest":
            output = ingest(args.snapshot, args.db)
        elif args.command == "status":
            output = status(args.db)
        else:
            output = backup(args.db, args.dest)
    except (ContinuityError, ValueError, OSError, sqlite3.Error) as exc:
        # Never echo input text or exception messages that could include
        # untrusted content, paths containing secrets, or raw SQL state.
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}))
        return 1
    print(json.dumps({"ok": True, **output}, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
