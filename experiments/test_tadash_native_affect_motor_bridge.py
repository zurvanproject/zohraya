"""Focused synthetic tests for real-body bridge logic; these tests DO NOT run MuJoCo."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from experiments import tadash_native_affect_motor_bridge as lab
from experiments import tadash_motion_episode as evidence


def fixture_native(command, friction, gain=.908869279232545):
    return {"schema":"native-v03-bilateral-shift/1","requested_shift_y_m":command,
            "friction":friction,"completed":True,"failure":None,"seconds_completed":4.,
            "held_com_y_delta_m":command*gain,"returned_com_y_delta_m":0.,
            "peak_tilt_deg":.05,"peak_motor_fraction":.64,
            "peak_joint_limit_excess_rad":0.,"last_half_second_max_speed":.0001,
            "both_feet_loaded_fraction":1.,"nonfoot_contacts":[],
            "trace":[{"t_s":i/20} for i in range(80)],
            "controller":"original_v03_contact_QP_both_feet_grounded",
            "no_weight_update":True,"no_root_actuator":True}


class NativeAffectMotorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).resolve().parents[1]/"docs"
        cls.motor=root/"tadash-motor-learning-independent-audit-20261102.json"
        cls.policy=root/"tadash-affect-decision-learning-ci-audit-20261102.json"

    def test_prior_audits_are_scoped_not_current_body_state(self):
        x=lab.load_inputs(self.motor,self.policy)
        self.assertGreater(x["command_gain"],1.)
        self.assertEqual(x["prior_policy"]["curious"],"explore")

    def test_bad_prior_source_provenance_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"fake.json"
            data=evidence.read(self.policy)
            data["workflow_run_id"]=0
            p.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,"prior synthetic"):
                lab.load_inputs(self.motor,p)

    def test_actual_reward_is_tracking_error_not_synthetic_affect(self):
        self.assertEqual(lab.native_reward(.002,.002),1.)
        self.assertAlmostEqual(lab.native_reward(.002,.001),.75)
        self.assertEqual(lab.native_reward(.002,-.003),0.)
        with self.assertRaises(ValueError):
            lab.native_reward(.004,0.)

    def test_action_commands_do_not_exceed_v03_limits(self):
        a=lab.load_inputs(self.motor,self.policy)
        for name,target in lab.ACTION_NOMINAL_M.items():
            self.assertLessEqual(target*a["command_gain"],.004)

    def test_context_menu_is_author_defined_not_derived_physiology(self):
        self.assertEqual(set(lab.CONTEXT_TARGETS),{"curious","frustrated","tired","steady"})
        self.assertEqual(lab.CONTEXT_TARGETS["tired"],0.)
        self.assertEqual(lab.ACTION_NOMINAL_M["rest"],0.)

    def test_feedback_ledger_replay_and_cold_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"ledger.sqlite"
            db=lab.Feedback(p)
            self.assertTrue(db.learn("training-1","curious","explore",.9,"a"*64))
            self.assertFalse(db.learn("training-1","curious","explore",.9,"a"*64))
            with self.assertRaisesRegex(ValueError,"Conflicting"):
                db.learn("training-1","curious","explore",.2,"a"*64)
            db.close()
            cold=lab.Feedback(p)
            n,mean=cold.db.execute("SELECT count,mean FROM q WHERE context='curious' AND action='explore'").fetchone()
            self.assertEqual((n,mean),(1,.9))
            cold.close()

    def test_holdout_feedback_cannot_train(self):
        with tempfile.TemporaryDirectory() as td:
            db=lab.Feedback(Path(td)/"ledger.sqlite")
            with self.assertRaisesRegex(ValueError,"Only training"):
                db.learn("holdout-1","steady","repeat",1.,"b"*64)
            with self.assertRaisesRegex(ValueError,"Finite numeric observation required"):
                db.learn("training-x","steady","repeat",float("nan"),"b"*64)
            db.close()

    def test_no_incomplete_policy_claim(self):
        with tempfile.TemporaryDirectory() as td:
            db=lab.Feedback(Path(td)/"ledger.sqlite")
            with self.assertRaisesRegex(ValueError,"Incomplete"):
                db.freeze()
            db.close()

    def test_all_same_policy_does_not_prove_native_action_selection(self):
        pairs=[{"context":c,"reward":{"native_learned":.8,"always_repeat":.8,
                 "prior_synthetic":.8}} for c in lab.CONTEXT_TARGETS for _ in range(2)]
        out=lab.score_pairs(pairs)
        self.assertFalse(out["better_than_repeat"])
        self.assertFalse(out["new_decision_learning_beyond_prior_demonstrated"])

    def test_prior_synthetic_tie_cannot_be_claimed_as_novelty(self):
        pairs=[{"context":c,"reward":{"native_learned":.95,"always_repeat":.5,
                 "prior_synthetic":.95}} for c in lab.CONTEXT_TARGETS for _ in range(2)]
        out=lab.score_pairs(pairs)
        self.assertTrue(out["better_than_repeat"])
        self.assertFalse(out["new_decision_learning_beyond_prior_demonstrated"])

    def test_native_end_to_end_mock_trains_and_evaluates_without_leakage(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            source=root/"motion"
            source.mkdir()
            seen=[]
            def fake_run(args,**kwargs):
                command,friction=float(args[-2]),float(args[-1])
                seen.append((command,friction))
                return SimpleNamespace(returncode=0,stdout=json.dumps(fixture_native(command,friction)),stderr="")
            with patch.object(evidence,"source_identity",return_value={"pin":"synthetic mocked test"}), \
                    patch.object(lab.subprocess,"run",side_effect=fake_run):
                result=lab.run(source,root/"out",self.motor,self.policy)
            self.assertEqual(result["native_trials"],40)
            self.assertEqual(result["heldout_pairs"],8)
            self.assertEqual(result["native_training_trials"],16)
            self.assertTrue(result["cold_recovered"])
            self.assertEqual(set(result["native_learned_policy"]),set(lab.CONTEXT_TARGETS))
            self.assertTrue(result["metrics"]["better_than_repeat"])
            self.assertFalse(result["metrics"]["new_decision_learning_beyond_prior_demonstrated"])
            self.assertEqual(len(seen),40)
            self.assertEqual(len(json.loads((root/"out"/"status.json").read_text())),2)

    def test_unknown_native_outcome_stops_before_next_trial(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            source=root/"motion";source.mkdir()
            with patch.object(evidence,"source_identity",return_value={"pin":"fixture"}), \
                    patch.object(lab.subprocess,"run",return_value=SimpleNamespace(returncode=3,stdout="",stderr="failed")) as called:
                with self.assertRaisesRegex(RuntimeError,"abnormally"):
                    lab.run(source,root/"out",self.motor,self.policy)
                self.assertEqual(called.call_count,1)
            status=json.loads((root/"out"/"status.json").read_text())
            self.assertEqual(status["status"],"failed_or_unknown")
            self.assertTrue(status["no_automatic_retry"])


if __name__=="__main__":
    unittest.main()
