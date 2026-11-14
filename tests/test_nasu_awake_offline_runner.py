"""Tests for a six-month offline runner; never calls remote services."""
import datetime as dt
import hashlib
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

if __name__=="__main__":
    unittest.main()

