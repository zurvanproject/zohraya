"""Synthetic boundary contracts: upstream self-consistency and durable import."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from . import bridge, core

T = datetime(2026, 11, 13, 9, tzinfo=timezone.utc)


def fake(rev=1, load=.25, time=1.6, occurred=False):
    sensory = {"time": time, "load": load, "prediction_error": .2, "ticks": int(time * 10)}
    prediction = {"occurred": occurred, "probability": .3}
    snap = {"schema": bridge.SOURCE_SCHEMA, "session_id": "nasuraya",
            "revision": rev, "actions_used": rev, "stopped": False,
            "body_profile": "tadash_reduced_78kg_v1", "backend": "workshop",
            "source_identity": "1" * 64, "model_sha": "2" * 64, "event_tail": "3" * 64,
            "sensory": sensory, "prediction": prediction,
            "dios": {"revision": rev, "goal": {"selected_goal": 1},
                     "sensory_hypothesis_review": {"stance": "ABSTAIN"}},
            "last_receipt": {"revision": rev, "model_sha": "2" * 64,
                             "prediction": prediction, "state_sha": bridge.upstream_hash(sensory),
                             "local_simulation_only": True, "outcome_matches_request": True},
            "external_actions_taken": 0, "subjective_experience_established": False}
    snap["snapshot_sha256"] = bridge.upstream_hash(snap)
    return snap


def reseal(snap):
    snap = deepcopy(snap)
    del snap["snapshot_sha256"]
    snap["snapshot_sha256"] = bridge.upstream_hash(snap)
    return snap


class AdapterContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def test_six_source_scoped_scalar_fields(self):
        observations, meta = bridge.extract(fake(), stream="fixture", observed_at=T)
        self.assertEqual(len(observations), 6)
        self.assertEqual({r["source_ref"] for r in observations}, {bridge.SOURCE_REF})
        self.assertEqual({r["sample_time"] for r in observations}, {1.6})
        self.assertEqual(meta["dios_goal"], 1)
        self.assertTrue(all(type(row["value"]) in (int,float,str,bool) for row in observations))

    def test_two_revisions_are_persisted_and_cause_temporal_question(self):
        a = bridge.import_snapshot(self.root, fake(), stream="fixture", observed_at=T)
        self.assertEqual(a["ingest"]["added"], len(bridge.METRICS))
        core.set_paused(self.root, False, T)
        first = core.tick(self.root, T)
        self.assertEqual(first["status"], "question_created")
        b = bridge.import_snapshot(self.root, fake(2, .85, 3.2, True), stream="fixture",
                                   observed_at=T + timedelta(minutes=15))
        self.assertEqual(b["ingest"]["added"], len(bridge.METRICS))
        after = core.tick(self.root, T + timedelta(minutes=15))
        self.assertEqual(after["kind"], "temporal_change")
        self.assertEqual(core.status(self.root)["counts"]["evidence"], len(bridge.METRICS) * 2)
        self.assertEqual(core.status(self.root)["counts"]["ticks"], 2)

    def test_repeat_is_idempotent_but_changed_same_revision_rejected(self):
        base = fake()
        bridge.import_snapshot(self.root, base, stream="fixture", observed_at=T)
        repeat = bridge.import_snapshot(self.root, base, stream="fixture", observed_at=T)
        self.assertEqual(repeat["ingest"]["duplicate"], len(bridge.METRICS))
        changed = fake(load=.8)
        changed["last_receipt"]["state_sha"] = bridge.upstream_hash(changed["sensory"])
        with self.assertRaisesRegex(ValueError, "conflicting event id"):
            bridge.import_snapshot(self.root, reseal(changed), stream="fixture", observed_at=T)
        self.assertEqual(core.status(self.root)["counts"]["evidence"], len(bridge.METRICS))

    def test_tamper_and_legacy_fail_closed(self):
        changed = fake()
        changed["sensory"]["load"] = .6
        with self.assertRaisesRegex(ValueError, "integrity mismatch"):
            bridge.extract(changed, stream="fixture", observed_at=T)
        changed = fake()
        changed["last_receipt"]["state_sha"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "receipt"):
            bridge.extract(reseal(changed), stream="fixture", observed_at=T)
        changed = fake()
        changed["stopped"] = True
        with self.assertRaisesRegex(ValueError, "pre-stop"):
            bridge.extract(reseal(changed), stream="fixture", observed_at=T)
        changed = fake()
        changed["body_profile"] = "tadash_legacy_195kg"
        with self.assertRaisesRegex(ValueError, "legacy"):
            bridge.extract(reseal(changed), stream="fixture", observed_at=T)

    def test_invalid_goal_and_clock_fail_closed(self):
        changed = fake()
        changed["dios"]["goal"]["selected_goal"] = None
        with self.assertRaisesRegex(ValueError, "goal"):
            bridge.extract(reseal(changed), stream="fixture", observed_at=T)
        changed = fake()
        changed["sensory"]["time"] = -1
        changed["last_receipt"]["state_sha"] = bridge.upstream_hash(changed["sensory"])
        with self.assertRaisesRegex(ValueError, "sample time"):
            bridge.extract(reseal(changed), stream="fixture", observed_at=T)
        with self.assertRaisesRegex(ValueError, "stream"):
            bridge.extract(fake(), stream="../path", observed_at=T)

if __name__ == "__main__":
    unittest.main()
