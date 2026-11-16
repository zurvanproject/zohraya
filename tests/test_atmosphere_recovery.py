import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from atmosphere_attestation import EvidenceOutbox, envelope_for, canonical
from atmosphere_recovery import create_snapshot, verify_sealed_backup, restore_to_new_directory
from test_atmosphere_attestation import NOW, keypair, row, sign


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.awake_dir = self.base / "live-awake"
        self.awake_dir.mkdir()
        self.awake_db = self.awake_dir / "awake.sqlite3"
        with sqlite3.connect(self.awake_db) as a:
            a.executescript("""
                CREATE TABLE control(name TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE evidence(id TEXT PRIMARY KEY,topic TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE TABLE questions(topic TEXT PRIMARY KEY,id TEXT,kind TEXT,question TEXT,evidence_hash TEXT,revision INT,created_at TEXT,updated_at TEXT);
                CREATE TABLE ticks(seq INTEGER PRIMARY KEY,at TEXT,status TEXT,topic TEXT);
                CREATE TABLE ledger(seq INTEGER PRIMARY KEY,at TEXT,action TEXT,detail TEXT);
            """)
        self.box = EvidenceOutbox(self.base / "primary-outbox" / "evidence_outbox.sqlite3")
        self.priv, self.root = keypair()
        self.env = envelope_for(row(), source_id="stage3-pr198", source_revision="a" * 64)
        self.box.stage([self.env], manifest=sign(self.priv, [self.env]), root=self.root, now=NOW)
        self.archive = self.base / "separate-backup" / "snap-001"
        self.unsigned = create_snapshot(awake_db=self.awake_db, outbox_db=self.box.path,
                                        archive_dir=self.archive, now=NOW)
        self.sealed = {**self.unsigned, "signature_ed25519": self.priv.sign(canonical(self.unsigned)).hex()}
        self.pin = hashlib.sha256(canonical(self.sealed)).hexdigest()

    def test_backup_has_real_sqlite_and_independent_pinned_receipt(self):
        self.assertTrue(verify_sealed_backup(self.archive, self.sealed, root=self.root,
                                              expected_receipt_sha256=self.pin))
        self.assertTrue((self.archive / "awake.sqlite3").is_file())

    def test_restore_is_non_destructive_and_fresh(self):
        target = self.base / "restored-new-memory"
        result = restore_to_new_directory(self.archive, target, self.sealed, root=self.root,
                                          expected_receipt_sha256=self.pin)
        self.assertEqual(result["status"], "RESTORED_FOR_OFFLINE_REVIEW")
        self.assertFalse(result["live_activated"])
        self.assertTrue((target / "awake.sqlite3").exists())
        self.assertTrue(self.awake_db.exists())

    def test_existing_target_cannot_be_overwritten(self):
        with self.assertRaises(FileExistsError):
            restore_to_new_directory(self.archive, self.awake_dir, self.sealed, root=self.root,
                                     expected_receipt_sha256=self.pin)

    def test_corrupt_backups_cannot_be_restored(self):
        with (self.archive / "evidence_outbox.sqlite3").open("ab") as f:
            f.write(b"damaged")
        with self.assertRaisesRegex(ValueError, "backup-file-hash-invalid"):
            restore_to_new_directory(self.archive, self.base / "untrusted", self.sealed,
                                     root=self.root, expected_receipt_sha256=self.pin)

    def test_receipt_forgery_does_not_suffice(self):
        rogue, _ = keypair()
        tampered = {**self.unsigned, "signature_ed25519": rogue.sign(canonical(self.unsigned)).hex()}
        with self.assertRaisesRegex(ValueError, "backup-signature-invalid"):
            verify_sealed_backup(self.archive, tampered, root=self.root,
                                 expected_receipt_sha256=hashlib.sha256(canonical(tampered)).hexdigest())

    def test_rollback_receipt_refused_by_external_pin(self):
        with self.assertRaisesRegex(ValueError, "external-backup-pin-mismatch"):
            verify_sealed_backup(self.archive, self.sealed, root=self.root,
                                 expected_receipt_sha256="0" * 64)

    def test_archive_cannot_be_in_live_source(self):
        with self.assertRaisesRegex(ValueError, "archive-must-not-be-under-source-directory"):
            create_snapshot(awake_db=self.awake_db, outbox_db=self.box.path,
                            archive_dir=self.awake_dir / "subdir", now=NOW)

    def test_delivered_without_awake_record_cannot_be_backed_up(self):
        self.box.delivered([self.env["event_id"]])
        with self.assertRaisesRegex(ValueError, "delivered-evidence-missing-in-awake"):
            create_snapshot(awake_db=self.awake_db, outbox_db=self.box.path,
                            archive_dir=self.base / "bad-backup", now=NOW)

    def test_unsigned_only_backup_rejected(self):
        with self.assertRaises(ValueError):
            verify_sealed_backup(self.archive, self.unsigned, root=self.root,
                                 expected_receipt_sha256=self.pin)

    def test_archive_directory_must_be_separate_and_new(self):
        with self.assertRaises(FileExistsError):
            create_snapshot(awake_db=self.awake_db, outbox_db=self.box.path,
                            archive_dir=self.archive, now=NOW)

if __name__ == "__main__":
    unittest.main()
