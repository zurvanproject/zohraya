"""Independent local ledger contracts: uncertainty must survive restart unchanged."""
import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path

from experiments.tadash_dual_episode_memory import DualEpisodeMemory, IntegrityError
from experiments.tadash_embodied_origin import source_identity
from experiments.test_tadash_dual_sense import fixture, drift


class DualEpisodeMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"dual-body-evidence.sqlite"
        self.memory=DualEpisodeMemory(self.path)
        self.source=source_identity()["sha256"]
        self.rest=fixture(source=self.source)

    def tearDown(self):
        self.memory.close()
        self.tmp.cleanup()

    def put(self,event="r0",ordinal=1,observed=None,expected=None,intent=0.):
        return self.memory.append(
            "body_session",event,ordinal,intent,self.rest,
            self.rest if expected is None else expected,
            self.rest if observed is None else observed)

    def test_empty_memory_does_not_fabricate_bodily_states(self):
        info=self.memory.summary("body_session")
        self.assertEqual(info["count"],0)
        self.assertIsNone(info["disagreement_or_abstention_fraction"])

    def test_two_modalities_conflict_preserved_after_cold_restart(self):
        self.put()
        spoof=drift(self.rest,"primary")
        result=self.put("r1",2,observed=spoof)
        self.assertEqual(result["state"],"sensor_disagreement")
        prior=self.memory.snapshot("body_session")
        self.memory.close()
        self.memory=DualEpisodeMemory(self.path)
        after=self.memory.snapshot("body_session")
        self.assertEqual(prior,after)
        summary=self.memory.summary("body_session")
        self.assertEqual(summary["state_counts"]["sensor_disagreement"],1)
        self.assertEqual(summary["state_counts"]["no_detectable_change"],1)
        self.assertEqual(summary["disagreement_or_abstention_fraction"],.5)
        self.assertTrue(summary["never_infers_consciousness_or_external_cause"])

    def test_recorded_uncertainty_not_reclassified_as_certainty(self):
        outcome=self.put("r0",1,observed=drift(self.rest,"pose"))
        self.assertEqual(outcome["state"],"sensor_disagreement")
        summary=self.memory.summary("body_session")
        self.assertEqual(summary["last_state"],"sensor_disagreement")
        self.assertEqual(summary["disagreement_or_abstention_fraction"],1.)

    def test_dual_spoof_remains_unknown_cause_in_memory(self):
        result=self.put(observed=drift(self.rest,"both"))
        self.assertEqual(result["state"],"agreement_unattributed_change")
        record=self.memory.snapshot("body_session")["events"][0]
        self.assertEqual(record["causal_origin"],"unknown")
        self.assertEqual(record["source_kind"],
                         "one_native_MuJoCo_solver_two_virtual_readouts")
        self.assertEqual(len(record["readout_digests_sha256"]),3)

    def test_exact_idempotency(self):
        first=self.put()
        second=self.put()
        self.assertFalse(first["replay"])
        self.assertTrue(second["replay"])
        self.assertEqual(first["event_hash"],second["event_hash"])
        self.assertEqual(self.memory.snapshot("body_session")["count"],1)

    def test_conflict_raises_and_preserves_record(self):
        self.put()
        with self.assertRaisesRegex(ValueError,"conflicting_replay"):
            self.put(observed=drift(self.rest,"primary"))
        self.assertEqual(self.memory.snapshot("body_session")["count"],1)

    def test_sequence_gap_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"ordinal_gap_or_replay"):
            self.put(ordinal=2)
        self.assertEqual(self.memory.snapshot("body_session")["count"],0)

    def test_wrong_source_rejected_before_transaction(self):
        invalid=copy.deepcopy(self.rest)
        invalid["pose"]["source_sha256"]="fabricated"
        with self.assertRaisesRegex(ValueError,"source_pin_or_readout_missing"):
            self.put(observed=invalid)
        self.assertEqual(self.memory.snapshot("body_session")["count"],0)

    def test_missing_modality_rejected(self):
        invalid=copy.deepcopy(self.rest)
        del invalid["pose"]
        with self.assertRaisesRegex(ValueError,"source_pin_or_readout_missing"):
            self.put(observed=invalid)

    def test_time_desync_rejected_and_not_stored(self):
        invalid=copy.deepcopy(self.rest)
        invalid["pose"]["frames"][4]["t_s"]+=.003
        with self.assertRaisesRegex(ValueError,"unverified_bodily_evidence"):
            self.put(observed=invalid)
        self.assertEqual(self.memory.snapshot("body_session")["count"],0)

    def test_damaged_hash_chain_detected_across_processes(self):
        self.put()
        self.memory.close()
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE dual_events SET payload_json=replace(payload_json,"
                       "'no_detectable_change','command_consistent')")
        self.memory=DualEpisodeMemory(self.path)
        with self.assertRaises(IntegrityError):
            self.memory.snapshot("body_session")

    def test_native_two_observers_are_persisted_with_cause_unknown(self):
        try:
            import mujoco
            import numpy as np
            from experiments.tadash_dual_sense import MODEL,capture_paired
        except ImportError:
            self.skipTest("native MuJoCo required in CI")
        source=source_identity(MODEL)
        model=mujoco.MjModel.from_xml_path(str(MODEL))
        rest=capture_paired(model,mujoco,np,source)
        motor=capture_paired(model,mujoco,np,source,command_nm=8.)
        ext=capture_paired(model,mujoco,np,source,external_torque_nm=35.)
        records=[
            ("quiet",rest,rest,rest,0.,"no_detectable_change"),
            ("motor",rest,motor,motor,8.,"command_consistent"),
            ("unexpected",rest,rest,ext,0.,"agreement_unattributed_change"),
        ]
        for idx,(label,ref,pred,obs,cmd,target) in enumerate(records,1):
            outcome=self.memory.append("real_native_trial",label,idx,cmd,ref,pred,obs)
            self.assertEqual(outcome["state"],target)
        initial=self.memory.snapshot("real_native_trial")
        self.memory.close()
        self.memory=DualEpisodeMemory(self.path)
        replay=self.memory.snapshot("real_native_trial")
        self.assertEqual(initial,replay)
        self.assertEqual(replay["count"],3)
        self.assertEqual(replay["events"][-1]["causal_origin"],"unknown")


if __name__=="__main__":
    unittest.main()
