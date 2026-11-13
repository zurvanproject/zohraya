"""Nasuraya 90-day continuity kit: offline SQLite backups, verification and drill.

Standard-library only. This is a stand-alone migration safety tool, NOT a
deployed VPS service. A local snapshot is NOT an encrypted offsite backup.
It does not call any LLM, network service, external command, or actuator.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import uuid

SCHEMA = "nasuraya-continuity-snapshot/1"
BACKUP_PREFIX = "snapshot-"
MIN_FREE_BYTES = 5 * 1024**3

@contextmanager
def sqlite_transaction(path):
    """Commit or rollback and ALWAYS close SQLite handles, including on Windows."""
    conn = sqlite3.connect(str(path), timeout=10)
    try:
        with conn:
            yield conn
    finally:
        conn.close()



def utc_now():
    return datetime.now(timezone.utc)


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_db(path):
    raw = Path(path).expanduser()
    if raw.is_symlink() or not raw.is_file() or raw.suffix.lower() not in (
        ".db", ".sqlite", ".sqlite3"
    ):
        raise ValueError("source_must_be_existing_regular_sqlite_file")
    return raw.resolve(strict=True)


def check_sqlite(path):
    """Check disk-format integrity without changing the backed-up database."""
    import urllib.parse
    uri = "file:" + urllib.parse.quote(Path(path).resolve().as_posix(), safe="/:") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchall()
    finally:
        conn.close()
    if result != [("ok",)]:
        raise ValueError("sqlite_integrity_check_failed")


def snapshot(source_paths, dest_root):
    """Online SQLite backup() avoids broken WAL copies. No arbitrary files."""
    if not source_paths:
        raise ValueError("no_database_sources")
    sources = [ensure_db(x) for x in source_paths]
    labels = [src.name for src in sources]
    if len(set(labels)) != len(labels):
        raise ValueError("source_basenames_must_be_unique")
    if len(sources) > 16:
        raise ValueError("too_many_databases")
    root = Path(dest_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    created = utc_now().strftime("%Y%m%dT%H%M%SZ")
    final = root / (BACKUP_PREFIX + created + "-" + uuid.uuid4().hex[:12])
    temp = Path(tempfile.mkdtemp(prefix=".creating-", dir=str(root)))
    if os.name != "nt":
        temp.chmod(0o700)
    try:
        entries = []
        for src in sources:
            target = temp / src.name
            if target.exists() or target.is_symlink():
                raise ValueError("duplicate_target")
            import urllib.parse
            uri = "file:" + urllib.parse.quote(src.as_posix(), safe="/:") + "?mode=ro"
            live = sqlite3.connect(uri, uri=True, timeout=10)
            copy = None
            try:
                copy = sqlite3.connect(str(target), timeout=10)
                live.backup(copy, pages=100, sleep=0.01)
            finally:
                if copy is not None:
                    copy.close()
                live.close()
            check_sqlite(target)
            if os.name != "nt":
                target.chmod(0o600)
            entries.append({
                "file": src.name,
                "sha256": digest_file(target),
                "bytes": target.stat().st_size,
                "sqlite_integrity": "ok",
            })
        manifest = {
            "schema": SCHEMA,
            "created_utc": utc_now().isoformat(timespec="seconds"),
            "file_count": len(entries),
            "files": entries,
            "note": "UNENCRYPTED LOCAL SNAPSHOT: encrypt for transport/offsite",
        }
        manifest_path = temp / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if os.name != "nt":
            manifest_path.chmod(0o600)
        os.replace(temp, final)
        return {"snapshot": str(final), "files": len(entries),
                "verified": verify(final)["verified"],
                "unencrypted": True}
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def verify(snapshot_dir):
    path = Path(snapshot_dir).expanduser()
    if path.is_symlink() or not path.is_dir():
        raise ValueError("missing_or_symlink_snapshot")
    path = path.resolve(strict=True)
    meta = path / "manifest.json"
    if meta.is_symlink() or not meta.is_file():
        raise ValueError("manifest_absent")
    data = json.loads(meta.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError("unknown_backup_schema")
    records = data.get("files")
    if not isinstance(records, list) or not 1 <= len(records) <= 16:
        raise ValueError("invalid_backup_inventory")
    if data.get("file_count") != len(records):
        raise ValueError("inventory_count_mismatch")
    seen = set()
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("invalid_inventory_entry")
        label = item.get("file")
        if (not isinstance(label, str) or not label or
                Path(label).name != label or "/" in label or "\\" in label or
                label in seen):
            raise ValueError("unsafe_backup_filename")
        seen.add(label)
        saved = path / label
        if saved.is_symlink() or not saved.is_file():
            raise ValueError("backup_file_missing_or_link")
        if (item.get("sha256") != digest_file(saved) or
                item.get("bytes") != saved.stat().st_size):
            raise ValueError("backup_file_hash_mismatch")
        check_sqlite(saved)
    return {"verified": True, "files": len(records), "schema": SCHEMA,
            "path": str(path)}


def restore_drill(snapshot_dir):
    """Restore to fresh disposable dir ONLY; never write over a live DB."""
    checked = verify(snapshot_dir)
    with tempfile.TemporaryDirectory(prefix="nasuraya-restore-drill-") as temp:
        target = Path(temp)
        labels = json.loads(
            (Path(snapshot_dir) / "manifest.json").read_text(encoding="utf-8")
        )["files"]
        for entry in labels:
            name = entry["file"]
            shutil.copy2(Path(snapshot_dir) / name, target / name)
            if digest_file(target / name) != entry["sha256"]:
                raise ValueError("restored_hash_mismatch")
            check_sqlite(target / name)
        return {"restored_in_disposable_dir": True,
                "no_live_database_modified": True, "files": checked["files"]}


def preflight(database_paths, backup_root, max_age_hours=48):
    """Non-sensitive red/yellow/green report for operation review."""
    root = Path(backup_root).expanduser()
    notes = []
    latest = None
    if not root.is_dir():
        notes.append("NO_LOCAL_BACKUP_DIRECTORY")
    else:
        candidates = [
            x for x in root.iterdir() if x.is_dir() and not x.is_symlink()
            and x.name.startswith(BACKUP_PREFIX)
        ]
        if candidates:
            latest = max(candidates, key=lambda x: x.stat().st_mtime)
            try:
                verify(latest)
            except (ValueError, OSError, sqlite3.Error, json.JSONDecodeError):
                notes.append("LATEST_LOCAL_BACKUP_FAILED_VERIFICATION")
            age = (utc_now().timestamp() - latest.stat().st_mtime) / 3600
            if age < -0.1 or age > max_age_hours:
                notes.append("LOCAL_BACKUP_MISSING_OR_STALE")
        else:
            notes.append("NO_COMPLETE_LOCAL_SNAPSHOT")
    for database in database_paths:
        try:
            db = ensure_db(database)
            check_sqlite(db)
        except (ValueError, OSError, sqlite3.Error):
            notes.append("ONE_SOURCE_DATABASE_NOT_VERIFIABLE")
    if root.exists():
        available = shutil.disk_usage(root).free
        if available < MIN_FREE_BYTES:
            notes.append("BACKUP_TARGET_HAS_LT_5G_FREE")
    else:
        available = None
    # The caller is responsible for confirming independent off-provider copies.
    notes.append("OFFSITE_COPY_AND_BILLING_NOT_VERIFIED_BY_THIS_TOOL")
    return {
        "status": "needs_action" if len(notes) > 1 else "requires_offsite_check",
        "issues": sorted(set(notes)),
        "source_count": len(database_paths),
        "local_snapshot_found": latest is not None,
        "free_backup_bytes": available,
        "no_network_requests_performed": True,
    }


def simulate_90_days(days=90):
    """Offline *simulation* of backup/restore, NOT 90 days of live uptime."""
    if not 1 <= days <= 180:
        raise ValueError("invalid_simulated_days")
    with tempfile.TemporaryDirectory(prefix="nasuraya-90day-drill-") as folder:
        root = Path(folder)
        live_db = root / "awake.sqlite3"
        dst = root / "backups"
        with sqlite_transaction(live_db) as db:
            db.execute("CREATE TABLE ticks (seq INTEGER PRIMARY KEY, day INTEGER)")
        receipts = []
        for day in range(1, days + 1):
            with sqlite_transaction(live_db) as db:
                db.execute("INSERT INTO ticks(day) VALUES (?)", (day,))
            if day == 1 or day % 30 == 0 or day == days:
                backup = snapshot([live_db], dst)
                receipt = restore_drill(backup["snapshot"])
                with sqlite_transaction(Path(backup["snapshot"]) / "awake.sqlite3") as db:
                    count = db.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
                if count != day or not receipt["restored_in_disposable_dir"]:
                    raise ValueError("offline_checkpoint_restore_failed")
                receipts.append({"simulated_day": day, "rows_recovered": count})
        return {
            "pass": bool(receipts and receipts[-1]["rows_recovered"] == days),
            "offline_days_simulated": days,
            "recovery_checkpoints": receipts,
            "requires_live_scheduler_test": True,
            "does_not_prove_llm_autonomy": True,
        }


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    sp = parser.add_subparsers(dest="command", required=True)
    a = sp.add_parser("backup")
    a.add_argument("--db", action="append", required=True)
    a.add_argument("--dest", required=True)
    v = sp.add_parser("verify")
    v.add_argument("--snapshot", required=True)
    d = sp.add_parser("restore-drill")
    d.add_argument("--snapshot", required=True)
    p = sp.add_parser("preflight")
    p.add_argument("--db", action="append", required=True)
    p.add_argument("--backup-root", required=True)
    s = sp.add_parser("simulate-90-days")
    s.add_argument("--days", type=int, default=90)
    args = parser.parse_args()
    try:
        if args.command == "backup":
            output = snapshot(args.db, args.dest)
        elif args.command == "verify":
            output = verify(args.snapshot)
        elif args.command == "restore-drill":
            output = restore_drill(args.snapshot)
        elif args.command == "preflight":
            output = preflight(args.db, args.backup_root)
        else:
            output = simulate_90_days(args.days)
        success = output.get("pass", True) and output.get("verified", True)
    except (ValueError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        output, success = {"error": type(exc).__name__ + ": " + str(exc)}, False
    print(json.dumps(output, sort_keys=True, ensure_ascii=False, indent=2))
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    cli()
