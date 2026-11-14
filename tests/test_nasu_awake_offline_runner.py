"""Tests for a six-month offline runner; never calls remote services."""
import datetime as dt
import hashlib
import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PATH=Path(__file__).resolve().parents[1]/"tools/nasu_awake_offline_runner.py"
spec=importlib.util.spec_from_file_location("awake_runner_under_test",PATH)
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        home=Path(self.temp.name)
        self.state=home/"awake-stage"
        self.state.mkdir()
        self.ledger=home/"continuity.sqlite3"
        with sqlite3.connect(self.ledger) as db:
            db.execute("""CREATE TABLE observations(id INTEGER PRIMARY KEY,
                        hour TEXT UNIQUE, observed_at TEXT, metrics TEXT,
                        previous TEXT, digest TEXT)""")
        self.clock=dt.datetime(2026,11,14,4,0,tzinfo=dt.timezone.utc)

    def add_record(self):
        hour="2026-11-14T02:00Z"
        at="2026-11-14T02:00:16+00:00"
        metrics=json.dumps({"load":0.14,"memory_kib":{"MemAvailable":14000000},
                            "disk_available_bytes":148000000000},sort_keys=True)
        previous="0"*64
        checksum=hashlib.sha256("\n".join((previous,hour,at,metrics)).encode()).hexdigest()
        with sqlite3.connect(self.ledger) as db:
            db.execute("INSERT INTO observations(hour,observed_at,metrics,previous,digest) VALUES(?,?,?,?,?)",
                       (hour,at,metrics,previous,checksum))

    def test_daily_observation_is_stable(self):
        self.add_record()
        with patch.object(runner,"LEDGER",self.ledger):
            one=runner.observations(self.clock)
            again=runner.observations(self.clock+dt.timedelta(hours=2))
        self.assertEqual(one,again)
        self.assertEqual(len(one),3)
        self.assertEqual({x["topic"] for x in one},
                         {"server.load","server.memory_available","server.disk_available"})
        self.assertTrue(all(x["source_ref"]=="tadash://server/telemetry" for x in one))

    def test_rejects_tampered_offline_observation(self):
        self.add_record()
        with sqlite3.connect(self.ledger) as db:
            db.execute("UPDATE observations SET metrics='{}'")
        with patch.object(runner,"LEDGER",self.ledger):
            with self.assertRaisesRegex(ValueError,"hash-chain"):
                runner.observations(self.clock)

    def test_hourly_sqlite_backup_is_stable(self):
        with sqlite3.connect(self.state/"awake.sqlite3") as db:
            db.execute("CREATE TABLE test(value INTEGER)")
            db.execute("INSERT INTO test VALUES(7)")
        with patch.object(runner,"HOME",Path(self.temp.name)),patch.object(runner,"STATE",self.state),patch.object(runner,"BACKUPS",self.state/"backups"):
            result=runner.sqlite_backup(self.clock)
            repeat=runner.sqlite_backup(self.clock)
        self.assertEqual(result["status"],"created")
        self.assertEqual(repeat["status"],"existing")
        path=self.state/"backups"/result["file"]
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("SELECT value FROM test").fetchone()[0],7)

    def test_current_state_uses_versioned_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            home=Path(td)
            path=home/"migration"/"working"/("a"*32)/"awake.sqlite3"
            path.parent.mkdir(parents=True)
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE proof(a INTEGER)")
            report=home/"migration"/"latest-import.json"
            report.write_text(json.dumps({"working_db":str(path)}))
            with patch.object(runner,"HOME",home):
                self.assertEqual(runner.awake_state_dir(),path.parent)

    def test_systemd_sandbox_allows_only_versioned_awake_state(self):
        installer=(Path(__file__).resolve().parents[1]/
                   "tools/install_nasu_awake_offline.sh").read_text()
        self.assertIn("/var/lib/nasuraya/migration/working",installer)
        self.assertIn("IPAddressDeny=any",installer)
        self.assertIn("NoNewPrivileges=true",installer)

    def test_no_activation_without_gate(self):
        with patch.object(runner,"CONTROL",Path(self.temp.name)/"no-gate"):
            self.assertFalse(runner.gate()["enabled"])

    @unittest.skipIf(os.geteuid()==0,"permission reproduction needs a non-root process")
    def test_wal_reader_needs_sidecars_but_keeps_ledger_unchanged(self):
        self.add_record()
        with sqlite3.connect(self.ledger) as db:
            db.execute("PRAGMA journal_mode=WAL")
        db.close()
        before=self.ledger.read_bytes()
        home=Path(self.temp.name)
        self.ledger.chmod(0o444)
        home.chmod(0o555)
        try:
            with patch.object(runner,"LEDGER",self.ledger):
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    runner.observations(self.clock)
            self.assertEqual(caught.exception.sqlite_errorcode & 255,sqlite3.SQLITE_READONLY)
        finally:
            home.chmod(0o700)
            self.ledger.chmod(0o600)
        with patch.object(runner,"LEDGER",self.ledger):
            self.assertEqual(len(runner.observations(self.clock)),3)
        self.assertEqual(self.ledger.read_bytes(),before)

    def test_telemetry_failure_does_not_resume_or_write_awake(self):
        (self.state/"awake.sqlite3").touch()
        core=Mock()
        with patch.object(runner.os,"geteuid",return_value=1000), \
             patch.object(runner,"locked_source",return_value=core), \
             patch.object(runner,"gate",return_value={"enabled":True}), \
             patch.object(runner,"awake_state_dir",return_value=self.state), \
             patch.object(runner,"observations",side_effect=sqlite3.OperationalError("readonly")):
            with self.assertRaises(sqlite3.OperationalError):
                runner.run(self.clock)
        core.status.assert_not_called()
        core.set_paused.assert_not_called()
        core.ingest.assert_not_called()
        core.tick.assert_not_called()

    def test_sandbox_permits_wal_sidecars_without_removing_confinement(self):
        installer=(Path(__file__).resolve().parents[1]/
                   "tools/install_nasu_awake_offline.sh").read_text()
        writable=next(x for x in installer.splitlines() if x.startswith("ReadWritePaths="))
        self.assertIn("/var/lib/nasuraya/continuity",writable.split("=",1)[1].split())
        self.assertIn("ProtectSystem=strict",installer)
        self.assertIn("RestrictAddressFamilies=AF_UNIX",installer)

if __name__=="__main__":
    unittest.main()

