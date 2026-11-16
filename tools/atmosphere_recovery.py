"""ATMOSPHERE: consistent SQLite snapshot and signed, non-destructive recovery.

This code never overwrites a live database, generates no cryptographic keys,
and cannot prove an off-host backup exists. Signing happens offline elsewhere.
"""
from __future__ import annotations
from contextlib import closing
from pathlib import Path
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import stat
import tempfile

from atmosphere_attestation import PinnedRoot, canonical, iso, sha, time_now

SCHEMA = "atmosphere-recovery/1"
REQUIRED = {
    "awake.sqlite3": {"control", "evidence", "questions", "ticks", "ledger"},
    "evidence_outbox.sqlite3": {"events"},
}
MAX_DB_BYTES = 100 * 1024 * 1024


def regular(path):
    p = Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_DB_BYTES:
        raise ValueError("missing-symlinked-or-oversized-database")
    return p


def inspect_sqlite(path, required):
    """Check actual SQLite contents rather than just the existence of a file."""
    path = regular(path)
    with closing(sqlite3.connect("file:" + str(path.resolve()) + "?mode=ro", uri=True)) as db:
        ok = db.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise ValueError("sqlite-integrity-failure")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required.issubset(tables):
            raise ValueError("missing-expected-tables")
        if "events" in required:
            state = {row[0] for row in db.execute("SELECT DISTINCT state FROM events")}
            if state - {"pending", "delivered"}:
                raise ValueError("unexpected-outbox-state")
    return True


def cross_check(awake, outbox):
    """A delivered event MUST exist in Awake; a pending event may or may not."""
    with (closing(sqlite3.connect("file:" + str(regular(awake).resolve()) + "?mode=ro", uri=True)) as a,
          closing(sqlite3.connect("file:" + str(regular(outbox).resolve()) + "?mode=ro", uri=True)) as o):
        imported = {r[0] for r in a.execute("SELECT id FROM evidence")}
        delivered = {r[0] for r in o.execute("SELECT id FROM events WHERE state='delivered'")}
        if not delivered.issubset(imported):
            raise ValueError("delivered-evidence-missing-in-awake")
        # Check per-event payload binding, not only the presence of an id.
        from atmosphere_attestation import payload_valid, canonical, sha
        for event_id, digest, raw in o.execute("SELECT id,digest,body FROM events WHERE state='delivered'"):
            body = json.loads(raw)
            payload_valid(body)
            if body["event_id"] != event_id or sha(canonical(body)) != digest:
                raise ValueError("outbox-body-digest-corrupted")
            awake_raw = a.execute("SELECT payload FROM evidence WHERE id=?", (event_id,)).fetchone()[0]
            evidence_row = {k: v for k, v in body.items() if k in
                            {"event_id", "topic", "source_ref", "observed_at", "sample_time", "confidence", "value"}}
            # Awake normalizes confidence and sample_time to float, timestamps to seconds.
            if json.loads(awake_raw) != {**evidence_row,
                                         "confidence": float(evidence_row["confidence"]),
                                         "sample_time": float(evidence_row["sample_time"])}:
                raise ValueError("awake-outbox-content-disagreement")


def _copy_sqlite(source, dest):
    regular(source)
    with (closing(sqlite3.connect("file:" + str(Path(source).resolve()) + "?mode=ro", uri=True)) as src,
          closing(sqlite3.connect(str(dest))) as out):
        src.backup(out)
    os.chmod(dest, 0o600)


def create_snapshot(*, awake_db, outbox_db, archive_dir, now):
    """Create an unsigned snapshot. Seal its receipt with an OFFLINE signer.

    Archive must be outside both source DB parents. No existing archive replaced.
    This is logically separate; off-host/off-disk separation is operator work.
    """
    dest = Path(archive_dir).absolute()
    sources = {"awake.sqlite3": regular(awake_db), "evidence_outbox.sqlite3": regular(outbox_db)}
    for source in sources.values():
        if dest == source.parent.resolve() or source.parent.resolve() in dest.parents:
            raise ValueError("archive-must-not-be-under-source-directory")
    if dest.exists() or dest.is_symlink():
        raise FileExistsError("archive-already-exists")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".atmosphere-backup-", dir=dest.parent) as temp:
        staging = Path(temp)
        files = []
        for name, original in sources.items():
            copied = staging / name
            _copy_sqlite(original, copied)
            inspect_sqlite(copied, REQUIRED[name])
            files.append({"name": name, "sha256": sha(copied.read_bytes()), "size": copied.stat().st_size})
        cross_check(staging / "awake.sqlite3", staging / "evidence_outbox.sqlite3")
        receipt = {"schema": SCHEMA, "created_at": iso(now), "files": sorted(files, key=lambda f: f["name"])}
        (staging / "UNSIGNED_RECEIPT.json").write_bytes(canonical(receipt))
        os.chmod(staging / "UNSIGNED_RECEIPT.json", 0o600)
        # Atomic folder publish; source files are left untouched.
        os.mkdir(dest, mode=0o700)
        for name in [*sources, "UNSIGNED_RECEIPT.json"]:
            os.replace(staging / name, dest / name)
    return receipt


def verify_sealed_backup(archive_dir, sealed_receipt, *, root, expected_receipt_sha256):
    """Require independent root *and* separately pinned receipt to prevent rollback."""
    if not isinstance(root, PinnedRoot) or type(sealed_receipt) is not dict:
        raise ValueError("invalid-backup-trust-context")
    if set(sealed_receipt) != {"schema", "created_at", "files", "signature_ed25519"}:
        raise ValueError("backup-receipt-shape")
    if sealed_receipt["schema"] != SCHEMA:
        raise ValueError("backup-schema")
    unsigned = {k: v for k, v in sealed_receipt.items() if k != "signature_ed25519"}
    if (not isinstance(expected_receipt_sha256, str) or len(expected_receipt_sha256) != 64
            or not hmac.compare_digest(sha(canonical(sealed_receipt)), expected_receipt_sha256)):
        raise ValueError("external-backup-pin-mismatch")
    if not root.verify(unsigned, sealed_receipt["signature_ed25519"]):
        raise ValueError("backup-signature-invalid")
    from atmosphere_attestation import utc
    utc(unsigned["created_at"])
    files = unsigned["files"]
    if type(files) is not list or len(files) != 2 or {f.get("name") for f in files if type(f) is dict} != set(REQUIRED):
        raise ValueError("backup-file-list-invalid")
    dest = Path(archive_dir)
    if dest.is_symlink() or not dest.is_dir():
        raise ValueError("backup-dir-invalid")
    for f in files:
        if type(f) is not dict or set(f) != {"name", "sha256", "size"}:
            raise ValueError("backup-file-entry-invalid")
        path = regular(dest / f["name"])
        if path.stat().st_size != f["size"] or not hmac.compare_digest(sha(path.read_bytes()), f["sha256"]):
            raise ValueError("backup-file-hash-invalid")
        inspect_sqlite(path, REQUIRED[f["name"]])
    cross_check(dest / "awake.sqlite3", dest / "evidence_outbox.sqlite3")
    return True


def restore_to_new_directory(archive_dir, target_dir, sealed_receipt, *, root, expected_receipt_sha256):
    """Fail-closed recovery. Refuses any existing target; never modifies live DBs."""
    verify_sealed_backup(archive_dir, sealed_receipt, root=root,
                         expected_receipt_sha256=expected_receipt_sha256)
    target = Path(target_dir).absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError("cannot-overwrite-existing-memory")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".atmosphere-restore-", dir=target.parent) as temp:
        staging = Path(temp)
        for name in REQUIRED:
            shutil.copyfile(Path(archive_dir) / name, staging / name)
            os.chmod(staging / name, 0o600)
        for name, required in REQUIRED.items():
            inspect_sqlite(staging / name, required)
        cross_check(staging / "awake.sqlite3", staging / "evidence_outbox.sqlite3")
        # Revalidate the archive right before publication; single-host, no writer-lock guarantee.
        verify_sealed_backup(archive_dir, sealed_receipt, root=root,
                             expected_receipt_sha256=expected_receipt_sha256)
        os.mkdir(target, mode=0o700)
        for name in REQUIRED:
            os.replace(staging / name, target / name)
    return {"status": "RESTORED_FOR_OFFLINE_REVIEW", "target": str(target),
            "authority": "none", "live_activated": False}
