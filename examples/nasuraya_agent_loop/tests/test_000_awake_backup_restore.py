"""Isolated recovery test for the newest hourly Awake backup on the Ubuntu VPS.

The existing GitHub Issue Bridge's fixed allowlisted "test" action runs these
unittest cases as the unprivileged nasuraya user after a reviewed repo sync.
No live database is opened or modified; no private backup data is uploaded.
GitHub CI without a private backup directory skips the host-only test.
"""
import hashlib
import hmac
import re
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

BACKUPS = Path("/var/lib/nasuraya/awake-backups")
HOURLY = re.compile(r"awake-\d{8}T\d{2}Z\.sqlite3\Z")
TABLES = ("evidence", "questions", "ticks", "ledger")
MAX_BYTES = 512 * 1024 * 1024


def latest_hourly(folder):
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Missing or redirected backup directory")
    choices = sorted(p for p in folder.iterdir() if HOURLY.fullmatch(p.name))
    if not choices:
        raise ValueError("No hourly Awake backup found")
    return choices[-1]


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def restore_probe(source):
    """Verify source checksum and execute an isolated write-rollback drill."""
    if source.is_symlink() or not source.is_file():
        raise ValueError("Untrusted backup file")
    size = source.stat().st_size
    if size <= 0 or size > MAX_BYTES:
        raise ValueError("Backup size out of bounds")
    marker = source.with_name(source.name + ".sha256")
    if marker.is_symlink() or not marker.is_file():
        raise ValueError("Missing or redirected checksum")
    words = marker.read_text(encoding="ascii").strip().split()
    if (len(words) != 2 or words[1] != source.name
            or not re.fullmatch(r"[a-f0-9]{64}", words[0])):
        raise ValueError("Malformed checksum manifest")
    expected = words[0]
    if not hmac.compare_digest(file_hash(source), expected):
        raise ValueError("Checksum mismatch")

    with tempfile.TemporaryDirectory(prefix="nasu-awake-restore-") as temp:
        restored = Path(temp) / "awake.sqlite3"
        shutil.copyfile(source, restored)
        if not hmac.compare_digest(file_hash(restored), expected):
            raise ValueError("Restored bytes differ from verified source")
        with sqlite3.connect(restored, timeout=10) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Restored SQLite failed integrity check")
            before = tuple(
                db.execute('SELECT COUNT(*) FROM "' + table + '"').fetchone()[0]
                for table in TABLES
            )
            db.execute("SAVEPOINT nasu_restore_probe")
            try:
                db.execute(
                    'CREATE TABLE "__nasu_restore_drill__" (value INTEGER NOT NULL)'
                )
                db.execute('INSERT INTO "__nasu_restore_drill__" VALUES (1)')
                assert db.execute(
                    'SELECT value FROM "__nasu_restore_drill__"'
                ).fetchone() == (1,)
            finally:
                db.execute("ROLLBACK TO SAVEPOINT nasu_restore_probe")
                db.execute("RELEASE SAVEPOINT nasu_restore_probe")
            after = tuple(
                db.execute('SELECT COUNT(*) FROM "' + table + '"').fetchone()[0]
                for table in TABLES
            )
            if after != before or db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE name='__nasu_restore_drill__'"
            ).fetchone():
                raise ValueError("Restore drill changed historical counts")

    if not hmac.compare_digest(file_hash(source), expected):
        raise ValueError("Original backup changed during restore drill")
    return dict(zip(TABLES, before))


class TestAwakeBackupRestore(unittest.TestCase):
    def test_000_host_hourly_backup_restores(self):
        if not BACKUPS.exists():
            self.skipTest("no private VPS backup directory (expected in CI)")
        counts = restore_probe(latest_hourly(BACKUPS))
        print("AWAKE_RESTORE=SUCCESS;CHECKSUM=OK;SQLITE=OK;"
              + ";".join(f"{key}={value}" for key, value in counts.items()),
              flush=True)

    def test_001_synthetic_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder / "awake-20261117T20Z.sqlite3"
            with sqlite3.connect(source) as db:
                for table in TABLES:
                    db.execute(
                        'CREATE TABLE "' + table + '" (id INTEGER PRIMARY KEY)'
                    )
                    db.execute(
                        'INSERT INTO "' + table + '" VALUES (1)'
                    )
            source.with_name(source.name + ".sha256").write_text(
                f"{file_hash(source)}  {source.name}\n", encoding="ascii"
            )
            self.assertEqual(restore_probe(source), dict.fromkeys(TABLES, 1))
            self.assertEqual(latest_hourly(folder), source)

    def test_002_checksum_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "awake-20261117T20Z.sqlite3"
            source.write_bytes(b"tampered backup")
            source.with_name(source.name + ".sha256").write_text(
                f"{'0' * 64}  {source.name}\n", encoding="ascii"
            )
            with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                restore_probe(source)


if __name__ == "__main__":
    unittest.main()
