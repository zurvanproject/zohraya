"""Synthetic adapter tests plus real PR#205 module test when source checkout is present."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import hashlib
import json
from contextlib import closing
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from atmosphere_attestation import PinnedRoot, canonical
from atmosphere_awake_adapter import ControlledAwakeAdapter
from test_atmosphere_attestation import NOW, keypair, sign

COMMIT = "d86750d8d26d4ea6a3fe595f9e1ee81e95d81fec"
FIELDS = ("sensory_load", "prediction_error", "sensory_occurrence", "goal_selected", "dios_sensory_stance", "action_matches")


def make_snapshot():
    """Construct a self-consistent *synthetic* PR198 Stage3 snapshot."""
    def digest(obj):
        return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                         allow_nan=False).encode()).hexdigest()
    sensory = {"time": 1.6, "load": .4, "prediction_error": .6}
    prediction = {"occurred": True}
    model_sha = "1" * 64
    snapshot = {
        "schema": "nasuraya.shared-session/3", "external_actions_taken": 0,
        "subjective_experience_established": False, "stopped": False,
        "body_profile": "tadash_reduced_78kg_v1", "backend": "workshop",
        "source_identity": "2" * 64, "model_sha": model_sha, "event_tail": "3" * 64,
        "session_id": "synthetic-contract", "revision": 1, "actions_used": 1,
        "sensory": sensory, "prediction": prediction,
        "dios": {"revision": 1, "goal": {"selected_goal": 1},
                 "sensory_hypothesis_review": {"stance": "needs_review"}},
        "last_receipt": {"revision": 1, "model_sha": model_sha,
                         "prediction": prediction, "local_simulation_only": True,
                         "state_sha": digest(sensory), "outcome_matches_request": True}}
    snapshot["snapshot_sha256"] = digest(snapshot)
    return snapshot


class StubBridge:
    SOURCE_COMMIT = COMMIT
    METRICS = FIELDS
    @staticmethod
    def extract(snapshot, *, stream, observed_at):
        prefix = "v3-synthetictest-1-"
        values = [.4, .6, True, 1, "needs_review", True]
        rows = [{"event_id": prefix + f, "topic": "shared." + stream + "." + f,
                 "source_ref": "https://github.com/zurvanproject/zohraya/commit/" + COMMIT,
                 "observed_at": "2026-11-15T17:00:00Z", "sample_time": 1.6,
                 "confidence": .7, "value": v} for f, v in zip(FIELDS, values)]
        return rows, {"source_commit": COMMIT, "snapshot_sha256": snapshot["snapshot_sha256"]}


class StubCore:
    @staticmethod
    def ingest(root, items, now=None):
        p = Path(root)
        p.mkdir(exist_ok=True, parents=True)
        with sqlite3.connect(p / "awake.sqlite3") as db:
            db.execute("CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY,topic TEXT,payload TEXT)")
            added = duplicates = 0
            for row in items:
                old = db.execute("SELECT payload FROM evidence WHERE id=?", (row["event_id"],)).fetchone()
                payload = {**row, "confidence": float(row["confidence"]), "sample_time": float(row["sample_time"])}
                encoded = json.dumps(payload, sort_keys=True)
                if old:
                    if json.loads(old[0]) != payload:
                        raise ValueError("conflicting-stub-awake-event")
                    duplicates += 1
                else:
                    db.execute("INSERT INTO evidence VALUES(?,?,?)", (row["event_id"], row["topic"], encoded))
                    added += 1
        db.close()
        return {"status": "ingested", "added": added, "duplicate": duplicates}


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.priv, self.root = keypair()
        self.snapshot = make_snapshot()
        self.adapter = ControlledAwakeAdapter(outbox_path=Path(self.tmp.name) / "outbox" / "evidence_outbox.sqlite3",
                                              awake_root=Path(self.tmp.name) / "awake",
                                              trusted_core_sha256="1" * 64, trusted_bridge_sha256="2" * 64)
        self.stub = patch.object(ControlledAwakeAdapter, "_modules", return_value=(StubCore, StubBridge))
        self.stub.start()
        self.addCleanup(self.stub.stop)

    def stage(self):
        envelopes, status = self.adapter.prepare_unsigned(self.snapshot, stream="demo", observed_at=NOW)
        self.assertEqual(status["status"], "UNSIGNED_NEEDS_INDEPENDENT_ATTESTATION")
        signed = sign(self.priv, envelopes)
        self.adapter.stage_signed(self.snapshot, stream="demo", observed_at=NOW,
                                  manifest=signed, root=self.root, now=NOW)
        return envelopes

    def test_six_signed_events_to_awake_without_dios_write_or_tick(self):
        self.stage()
        result = self.adapter.deliver_pending(root=self.root, now=NOW)
        self.assertEqual((result["status"], result["delivered"], result["dios_actions"]),
                         ("DELIVERED_TO_AWAKE_REVIEW_ONLY", 6, 0))
        self.assertFalse(result["awake_tick_started"])
        self.assertEqual(self.adapter.outbox.stats(), {"pending": 0, "delivered": 6})

    def test_crash_between_awake_commit_and_outbox_mark_recovers_idempotently(self):
        self.stage()
        with patch.object(self.adapter.outbox, "delivered", side_effect=RuntimeError("mock-crash")):
            with self.assertRaisesRegex(RuntimeError, "mock-crash"):
                self.adapter.deliver_pending(root=self.root, now=NOW)
        receipt = self.adapter.deliver_pending(root=self.root, now=NOW)
        self.assertEqual((receipt["added"], receipt["duplicate"]), (0, 6))
        self.assertEqual(self.adapter.outbox.stats()["delivered"], 6)

    def test_preexisting_world_writable_awake_dir_is_rejected(self):
        self.stage()
        self.adapter.awake_root.mkdir(mode=0o777)
        self.adapter.awake_root.chmod(0o777)
        with self.assertRaisesRegex(ValueError, "awake-directory-permissions-insecure"):
            self.adapter.deliver_pending(root=self.root, now=NOW)
        self.assertEqual(self.adapter.outbox.stats()["pending"], 6)

    def test_awake_dir_created_with_restricted_permissions(self):
        self.stage()
        self.adapter.deliver_pending(root=self.root, now=NOW)
        self.assertEqual(self.adapter.awake_root.stat().st_mode & 0o077, 0)

    def test_unsigned_prepare_has_no_database_side_effects(self):
        _, status = self.adapter.prepare_unsigned(self.snapshot, stream="demo", observed_at=NOW)
        self.assertFalse(self.adapter.awake_root.exists())
        self.assertEqual(self.adapter.outbox.stats()["pending"], 0)

    def test_wrong_signature_leaves_both_memories_unchanged(self):
        envelopes, _ = self.adapter.prepare_unsigned(self.snapshot, stream="demo", observed_at=NOW)
        rogue, _ = keypair()
        with self.assertRaisesRegex(ValueError, "invalid-signature"):
            self.adapter.stage_signed(self.snapshot, stream="demo", observed_at=NOW,
                                      manifest=sign(rogue, envelopes), root=self.root, now=NOW)
        self.assertFalse(self.adapter.awake_root.exists())
        self.assertEqual(self.adapter.outbox.stats()["pending"], 0)

    def test_replacing_one_scalar_after_signed_attestation_rejects_bundle(self):
        env, _ = self.adapter.prepare_unsigned(self.snapshot, stream="demo", observed_at=NOW)
        attested = sign(self.priv, env)
        original = StubBridge.extract
        def adversarial(snap, *, stream, observed_at):
            rows, r = original(snap, stream=stream, observed_at=observed_at)
            rows[0]["value"] = 99
            return rows, r
        with patch.object(StubBridge, "extract", side_effect=adversarial):
            with self.assertRaisesRegex(ValueError, "signed-commitment-mismatch"):
                self.adapter.stage_signed(self.snapshot, stream="demo", observed_at=NOW,
                                          manifest=attested, root=self.root, now=NOW)
        self.assertEqual(self.adapter.outbox.stats()["pending"], 0)


class ActualPR205ContractTests(unittest.TestCase):
    """Runs against real checked-out PR#205 in CI via PYTHONPATH, not stubs."""
    def test_real_original_bridge_and_awake_core(self):
        try:
            from tadash_awake import bridge, core
        except ImportError:
            self.skipTest("pinned PR205 source not present locally; workflow checks out source")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            priv, root = keypair()
            adapter = ControlledAwakeAdapter(outbox_path=base / "evidence_outbox.sqlite3",
                                             awake_root=base / "awake",
                                             trusted_core_sha256=hashlib.sha256(Path(core.__file__).read_bytes()).hexdigest(),
                                             trusted_bridge_sha256=hashlib.sha256(Path(bridge.__file__).read_bytes()).hexdigest())
            snapshot = make_snapshot()
            env, _ = adapter.prepare_unsigned(snapshot, stream="demo", observed_at=NOW)
            self.assertEqual(len(env), 6)
            result = adapter.stage_signed(snapshot, stream="demo", observed_at=NOW,
                                          manifest=sign(priv, env), root=root, now=NOW)
            self.assertEqual(result["added"], 6)
            delivery = adapter.deliver_pending(root=root, now=NOW)
            self.assertEqual(delivery["added"], 6)
            self.assertEqual(core.status(base / "awake")["counts"]["evidence"], 6)
            self.assertTrue(core.status(base / "awake")["paused"])
            self.assertEqual(adapter.deliver_pending(root=root, now=NOW)["status"], "IDLE")

if __name__ == "__main__":
    unittest.main()
