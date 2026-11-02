"""Synthetic evidence-integrity tests; these do not execute MuJoCo."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import tadash_motion_episode as lab


def fixture(folder):
    identity = {"commit": lab.MOTION_COMMIT, "model_path": lab.MODEL_PATH, "model_sha256": lab.MODEL_SHA256}
    contract = {"files": {"nasuraya.xml": lab.MODEL_SHA256}, "packages": {"mujoco": "fixture-only"}}
    payload = {"schema": "nasuraya-articulated-checkpoint/2",
               "contract": {"source": contract, "geometry_support": True, "compiled_model_sha256": "fixture"},
               "integration": [13., 0.01, 0.0], "qpos": [.01, 0., 1.], "qvel": [.001, 0., 0.], "time": 13.}
    checkpoint = {"value": payload, "sha256": lab.digest(payload)}
    result = {"requested_steps": 1, "accepted_steps": 1, "walk_pass": True, "failure": None,
              "nonfoot_ground_contacts": [], "max_tilt_deg": .6, "max_joint_limit_excess_rad": 0.,
              "final_max_generalized_speed": .001, "max_motor_torque_fraction": .99,
              "pelvis_displacement_xyz_m": [.01, 0., 0.], "start_time": 2., "end_time": 13.,
              "final_qpos": payload["qpos"], "final_qvel": payload["qvel"], "checkpoint": checkpoint}
    receipt = {"command_id": "first", "command": lab.COMMAND, "result": result}
    session = {"schema": "nasuraya-motion-session/1", "status": "ready", "used_steps": 1, "max_steps": 2,
               "commands": [{"id": "first", "command": lab.COMMAND, "steps": 1, "status": "completed"}],
               "checkpoint": checkpoint}
    expectation = {"source": identity, "limits": lab.LIMITS, "command": lab.COMMAND, "learned_prediction": False}
    objects = {"first-receipt.json": receipt, "first-session.json": session,
               "model-audit.json": {"source_contract": contract}, "expectation.json": expectation,
               "capture-first.json": {"fixture_only": True}}
    for name, value in objects.items():
        lab.write(folder / name, value)
    motion = folder / "first-motion"
    motion.mkdir()
    lab.write(motion / "first.json", receipt)
    lab.write(motion / "session.json", session)
    (motion / "first.npz").write_bytes(b"unit fixture only; actual CLI additionally validates NPZ")
    episode = {"schema": lab.EPISODE_SCHEMA, "source": identity, "intention": expectation,
               "observation": lab.observation_of(result), "evidence": {name: lab.sha(folder / name) for name in objects},
               "motion_snapshot": "first-motion", "motion_files": lab.tree_hashes(motion),
               "harness_sha256": lab.sha(Path(lab.__file__))}
    lab.write(folder / "episode.json", episode)
    return identity, objects, episode


class EvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.identity, self.objects, self.episode = fixture(self.folder)
        self.anchor = lab.sha(self.folder / "episode.json")

    def tearDown(self):
        self.temporary.cleanup()

    def recover(self):
        return lab.recover_episode(self.folder, self.anchor, self.identity)

    def resave_consistent_fixture(self):
        """Re-anchor intentionally invalid fixtures to test semantic gates, not only hashing."""
        for name, value in self.objects.items():
            lab.write(self.folder / name, value, replace=True)
        self.episode["evidence"] = {name: lab.sha(self.folder / name) for name in self.objects}
        lab.write(self.folder / "episode.json", self.episode, replace=True)
        self.anchor = lab.sha(self.folder / "episode.json")

    def test_complete_evidence_selects_only_fixed_second_step(self):
        decision = self.recover()
        self.assertEqual(decision["decision"], "execute_second_one_step")
        self.assertFalse(decision["learned_policy"])
        self.assertFalse(decision["quality_improvement_established"])

    def test_raw_receipt_tamper_rejected_before_action(self):
        (self.folder / "first-receipt.json").write_text("{}")
        with patch.object(lab.subprocess, "Popen") as process:
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                self.recover()
            process.assert_not_called()

    def test_pose_capture_tamper_rejected(self):
        (self.folder / "first-motion/first.npz").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Raw motion"):
            self.recover()

    def test_episode_changes_do_not_replace_parent_anchor(self):
        self.episode["observation"]["max_tilt_deg"] = 0.
        lab.write(self.folder / "episode.json", self.episode, replace=True)
        with self.assertRaisesRegex(ValueError, "anchor mismatch"):
            self.recover()

    def test_different_model_source_rejected(self):
        self.identity = {**self.identity, "model_sha256": "0" * 64}
        with self.assertRaisesRegex(ValueError, "source identity"):
            self.recover()

    def test_missing_evidence_cannot_trigger_action(self):
        (self.folder / "first-session.json").unlink()
        with patch.object(lab.subprocess, "Popen") as process:
            with self.assertRaises(FileNotFoundError):
                self.recover()
            process.assert_not_called()

    def test_failed_and_unresolved_sessions_block(self):
        for kind in ("failed", "unresolved", "pending"):
            with self.subTest(kind=kind):
                state = self.objects["first-session.json"]
                state["commands"][0]["status"] = kind
                self.resave_consistent_fixture()
                with self.assertRaisesRegex(ValueError, "unresolved"):
                    self.recover()

    def test_failed_motion_not_promoted_by_complete_session(self):
        self.objects["first-receipt.json"]["result"]["walk_pass"] = False
        self.resave_consistent_fixture()
        with self.assertRaisesRegex(ValueError, "did not pass"):
            self.recover()

    def test_checkpoint_contract_drift_rejected(self):
        self.objects["model-audit.json"]["source_contract"] = copy.deepcopy(self.objects["model-audit.json"]["source_contract"])
        self.objects["model-audit.json"]["source_contract"]["packages"]["mujoco"] = "different"
        self.resave_consistent_fixture()
        with self.assertRaisesRegex(ValueError, "identity differs"):
            self.recover()

    def test_boundaries_must_agree_with_checkpoint(self):
        result = self.objects["first-receipt.json"]["result"]
        result["final_qpos"] = [99., 0., 1.]
        self.resave_consistent_fixture()
        with self.assertRaisesRegex(ValueError, "boundary differs"):
            self.recover()

    def test_pre_action_contract_cannot_be_relaxed(self):
        expectation = self.objects["expectation.json"]
        expectation["limits"] = {**lab.LIMITS, "max_tilt_deg": 90.}
        self.resave_consistent_fixture()
        with self.assertRaisesRegex(ValueError, "expectation mismatch"):
            self.recover()

    def test_intention_and_raw_expectation_must_agree(self):
        self.episode["intention"] = {**self.episode["intention"], "command": "other"}
        self.resave_consistent_fixture()
        with self.assertRaisesRegex(ValueError, "intention differs"):
            self.recover()

    def test_existing_output_rejected_without_native_process_or_retry(self):
        with patch.object(lab, "source_identity", return_value=self.identity), patch.object(lab.subprocess, "Popen") as process:
            with self.assertRaises(FileExistsError):
                lab.run_episode(self.folder, self.folder)
            process.assert_not_called()

    def test_physical_continuity_includes_full_integration(self):
        first = self.objects["first-receipt.json"]["result"]
        first["steps"] = [{"swing_side": 0}]
        second = {"initial_qpos": first["final_qpos"], "initial_qvel": first["final_qvel"],
                  "start_time": first["end_time"], "initial_integration_sha256": lab.digest(first["checkpoint"]["value"]["integration"]),
                  "continued_from": first["checkpoint"]["sha256"], "initialization_seconds": 0., "steps": [{"swing_side": 1}]}
        self.assertTrue(all(lab.continuity(first, second).values()))
        second["initial_integration_sha256"] = "0" * 64
        self.assertFalse(lab.continuity(first, second)["integration_exact"])


if __name__ == "__main__":
    unittest.main()
