import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from continuity import sample


class ContinuityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        native = self.root / "NasurayaTadashV1"
        self.dbfile = native / "state" / "session.sqlite"
        self.dbfile.parent.mkdir(parents=True)
        (self.root / "config.json").write_text(json.dumps(dict(tadash_root=str(native), installation_id="fixture")))
        self.health = self.root / "health.json"
        self.health.write_text(json.dumps(dict(installation_id="fixture", state="idle", updated_epoch=90)))
        with sqlite3.connect(self.dbfile) as db:
            db.execute("CREATE TABLE runtime (key TEXT, value TEXT)")
            db.execute("INSERT INTO runtime VALUES(?,?)", ("nasuraya-vps-body", '{"payload":{"revision":1}}'))
            db.execute("CREATE TABLE decisions(record TEXT)")
            db.execute("INSERT INTO decisions VALUES(?)",
                       ('{"selected_action":"observe","status":"complete","actual_outcome":{"body_checkpoint":{}}}',))
            db.execute("INSERT INTO decisions VALUES(?)",
                       ('{"selected_action":"walk","status":"complete","actual_outcome":{"status":"failed"}}',))

    def test_fresh_complete_ledger_stays_identical(self):
        before = self.dbfile.read_bytes()
        result = sample(self.root, now=100)
        self.assertTrue(result["ok"])
        self.assertEqual((result["native_cycles"], result["native_revision"], result["unresolved"]), (1, 1, 0))
        self.assertEqual(self.dbfile.read_bytes(), before)

    def test_stale_pending_and_unknown_are_visible(self):
        with sqlite3.connect(self.dbfile) as db:
            db.execute("INSERT INTO decisions VALUES(?)", ('{"selected_action":"walk","status":"running"}',))
        stale = sample(self.root, now=150)
        self.assertEqual(stale["issues"], ["stale_heartbeat", "unresolved_native"])
        self.assertEqual((stale["native_cycles"], stale["unresolved"]), (1, 1))
        self.health.unlink()
        missing = sample(self.root, now=100)
        self.assertIsNone(missing["heartbeat_fresh"])
        self.assertEqual(missing["native_revision"], 1)
        self.dbfile.unlink()
        self.assertIsNone(sample(self.root, now=100)["native_revision"])
        self.assertFalse(self.dbfile.exists())


if __name__ == "__main__":
    unittest.main()
