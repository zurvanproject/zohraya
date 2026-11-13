"""Local memory durability, provenance, conflicts and tamper detection."""
import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path

from experiments.tadash_body_episode_memory import BodyEventLedger, IntegrityError
from experiments.tadash_embodied_origin import source_identity
from experiments.test_tadash_temporal_proprioception import fixture


class BodyEventLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "body-events.sqlite"
        self.store = BodyEventLedger(self.db_path)
        self.source = source_identity()["sha256"]
        self.rest = fixture(source=self.source)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def record(self, event_id="one", ordinal=1, actual=None, intent=0., prediction=None):
        return self.store.append("trialA", event_id, ordinal, intent,
                                 self.rest,
                                 self.rest if prediction is None else prediction,
                                 self.rest if actual is None else actual)

    def test_initial_empty_has_genesis(self):
        snapshot = self.store.snapshot("trialA")
        self.assertEqual(snapshot["count"], 0)
        self.assertEqual(snapshot["head"], "0" * 64)

    def test_cold_restart_preserves_body_evidence_and_hashes(self):
        receipt1 = self.record()
        changed = fixture(
            source=self.source, tail=[.03*i for i in range(12)],
            pelvis=[.03*i for i in range(12)])
        receipt2 = self.record("two", 2, actual=changed)
        self.assertNotEqual(receipt1["event_hash"], receipt2["event_hash"])
        original = self.store.snapshot("trialA")
        self.store.close()
        self.store = BodyEventLedger(self.db_path)
        loaded = self.store.snapshot("trialA")
        self.assertEqual(loaded, original)
        self.assertEqual([e["payload"]["assessment_state"]
                          for e in loaded["events"]],
                         ["no_detectable_change", "unexplained_change"])

    def test_exact_event_replay_idempotent(self):
        receipt = self.record()
        duplicate = self.record()
        self.assertEqual(duplicate["event_hash"], receipt["event_hash"])
        self.assertTrue(duplicate["replay"])
        self.assertEqual(self.store.snapshot("trialA")["count"], 1)

    def test_conflicting_event_id_rejected_without_write(self):
        self.record()
        with self.assertRaisesRegex(ValueError, "duplicate_event_conflict"):
            self.record(intent=0., actual=fixture(source=self.source, tail=[.1]*12))
        self.assertEqual(self.store.snapshot("trialA")["count"], 1)

    def test_nonmonotone_or_gap_ordinal_rejected(self):
        with self.assertRaisesRegex(ValueError, "nonmonotone_or_gap_ordinal"):
            self.record(ordinal=3)
        self.assertEqual(self.store.snapshot("trialA")["count"], 0)

    def test_invalid_session_id_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_event_identifier"):
            self.store.append("trialA';DROP", "e1", 1, 0.,
                              self.rest, self.rest, self.rest)

    def test_nan_observation_rejected_not_laundered(self):
        bad = copy.deepcopy(self.rest)
        bad["frames"][0]["tail_yaw_rad"] = float("nan")
        with self.assertRaisesRegex(ValueError, "source_untrusted"):
            self.record(actual=bad)
        self.assertEqual(self.store.snapshot("trialA")["count"], 0)

    def test_unknown_source_rejected(self):
        bad = fixture(source="not_source")
        with self.assertRaisesRegex(ValueError, "source_untrusted"):
            self.record(actual=bad)

    def test_unverified_intent_rejected(self):
        act = fixture(command=8., tail=[.1]*12, source=self.source)
        with self.assertRaisesRegex(ValueError, "unverified_command"):
            self.record(intent=7., prediction=act, actual=act)

    def test_hash_chain_tamper_detection_on_reopen(self):
        self.record()
        self.store.close()
        # An accidental or malicious edit to stored payload invalidates the chain.
        with sqlite3.connect(str(self.db_path)) as db:
            db.execute("UPDATE events SET payload_json = replace(payload_json,"
                       " 'no_detectable_change', 'command_consistent')")
        self.store = BodyEventLedger(self.db_path)
        with self.assertRaises(IntegrityError):
            self.store.snapshot("trialA")

    def test_session_head_tamper_detection(self):
        self.record()
        self.store.db.execute(
            "UPDATE sessions SET head_hash = ? WHERE session_id = ?",
            ("f" * 64, "trialA"))
        with self.assertRaisesRegex(IntegrityError, "session_head_mismatch"):
            self.store.snapshot("trialA")

    def test_multi_session_isolation(self):
        self.record()
        self.store.append("trialB", "one", 1, 0.,
                          self.rest, self.rest, self.rest)
        self.assertEqual(self.store.snapshot("trialA")["count"], 1)
        self.assertEqual(self.store.snapshot("trialB")["count"], 1)


if __name__ == "__main__":
    unittest.main()
