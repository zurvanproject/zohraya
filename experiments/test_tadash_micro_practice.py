"""Synthetic unit tests for the finite curriculum; never count as native motion."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from experiments import tadash_micro_practice as p
from experiments import tadash_motion_episode as old


def native(stride=.015, success=True):
    cp = {"schema": "nasuraya-articulated-checkpoint/2",
          "qpos": [0., 0., 1.7], "qvel": [0., 0., 0.]}
    return {"requested_steps": 1, "accepted_steps": 1 if success else 0,
            "stride_m": stride, "walk_pass": success,
            "failure": None if success else "measured support loading gate timed out",
            "nonfoot_ground_contacts": [], "max_tilt_deg": .4,
            "max_joint_limit_excess_rad": .0, "final_max_generalized_speed": .001,
            "max_motor_torque_fraction": .99, "start_time": 2., "end_time": 13.,
            "simulated_seconds": 11., "checkpoint": {"value": cp, "sha256": old.digest(cp)} if success else None,
            "final_qpos": cp["qpos"], "final_qvel": cp["qvel"]}


def record(level, outcome):
    return {"level": level, "outcome": outcome}


class CurriculumTests(unittest.TestCase):
    def test_levels_small_and_bounded(self):
        self.assertEqual(p.LEVELS, (.0075, .015, .03, .06))
        self.assertEqual(p.MAX_ATTEMPTS, 4)

    def test_repeat_before_promote(self):
        self.assertEqual(p.next_level(1, [record(1, "met")]), (1, "repeat_same_easy_action"))
        self.assertEqual(p.next_level(1, [record(1, "met"), record(1, "met")]), (2, "promote_after_two"))

    def test_failure_simplifies_even_after_success(self):
        self.assertEqual(p.next_level(2, [record(2, "met"), record(2, "not_met")]),
                         (1, "simplify_after_failure"))

    def test_floor_failure_stops(self):
        self.assertEqual(p.next_level(0, [record(0, "not_met")]), (None, "stop_at_smallest"))

    def test_at_max_success_stops(self):
        self.assertEqual(p.next_level(3, [record(3, "met"), record(3, "met")]),
                         (None, "max_level_passed"))

    def test_invalid_decision_rejected(self):
        with self.assertRaises(ValueError):
            p.next_level(1, [record(0, "met")])
        with self.assertRaises(ValueError):
            p.next_level(1, [record(1, "unknown")])

    def test_native_success_verifies_checkpoint_and_bounds(self):
        self.assertEqual(p.assess(native(), .015), "met")
        bad = native()
        bad["checkpoint"]["value"]["qpos"] = [9, 8, 7]
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            p.assess(bad, .015)

    def test_native_explicit_failure_is_only_backoff_trigger(self):
        self.assertEqual(p.assess(native(success=False), .015), "not_met")
        unknown = native(success=False)
        unknown["failure"] = None
        with self.assertRaisesRegex(ValueError, "unknown"):
            p.assess(unknown, .015)

    def test_unsafe_success_rejected_not_promoted(self):
        for key, value in (("max_tilt_deg", 25.), ("nonfoot_ground_contacts", ["pelvis"]),
                           ("final_max_generalized_speed", .08),
                           ("max_motor_torque_fraction", float("nan"))):
            with self.subTest(key=key):
                sample = native()
                sample[key] = value
                with self.assertRaises(ValueError):
                    p.assess(sample, .015)

    def test_wrong_stride_and_nonfinite_rejected(self):
        with self.assertRaisesRegex(ValueError, "stride"):
            p.assess(native(stride=.06), .015)
        result = native()
        result["max_tilt_deg"] = float("inf")
        with self.assertRaises(ValueError):
            p.assess(result, .015)

    def test_tiny_offline_mock_demonstrates_two_levels_but_no_learning_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            output = root / "episode"
            strides = []
            def child(cmd, **kwargs):
                stride = float(cmd[-1])
                strides.append(stride)
                return SimpleNamespace(returncode=0, stdout=json.dumps(native(stride)), stderr="")
            identity = {"commit": old.MOTION_COMMIT, "model_path": old.MODEL_PATH,
                        "model_sha256": old.MODEL_SHA256}
            with patch.object(old, "source_identity", return_value=identity), \
                 patch.object(p.subprocess, "run", side_effect=child):
                summary = p.run(source, output)
            self.assertEqual(strides, [.015, .015, .03, .03])
            self.assertEqual(summary["trials"], 4)
            self.assertFalse(summary["learned_improvement_established"])
            self.assertEqual(json.loads((output / "status.json").read_text())["status"], "complete")
            self.assertEqual(len(summary["receipts"]), 4)

    def test_explicit_failure_backoff_and_no_repeat_on_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            seen = []
            def child(cmd, **kwargs):
                stride = float(cmd[-1])
                seen.append(stride)
                return SimpleNamespace(returncode=0, stdout=json.dumps(native(stride, success=stride != .015)), stderr="")
            with patch.object(old, "source_identity", return_value={"source": "fixture"}), \
                 patch.object(p.subprocess, "run", side_effect=child):
                summary = p.run(source, root / "out", max_attempts=3)
            self.assertEqual(seen, [.015, .0075, .0075])
            self.assertEqual(summary["observed_outcomes"], ["not_met", "met", "met"])

    def test_timeout_blocks_any_continuation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            from subprocess import TimeoutExpired
            with patch.object(old, "source_identity", return_value={"source": "fixture"}), \
                 patch.object(p.subprocess, "run", side_effect=TimeoutExpired("native", 1)) as child:
                with self.assertRaises(TimeoutError):
                    p.run(source, root / "out")
                self.assertEqual(child.call_count, 1)
            status = json.loads((root / "out" / "status.json").read_text())
            self.assertEqual(status["status"], "failed_or_unknown")
            self.assertTrue(status["no_automatic_retry"])

    def test_existing_folder_fails_before_any_native_call(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            output = root / "out"
            output.mkdir()
            with patch.object(old, "source_identity", return_value={"source": "fixture"}), \
                 patch.object(p.subprocess, "run") as child:
                with self.assertRaises(FileExistsError):
                    p.run(source, output)
                child.assert_not_called()


if __name__ == "__main__":
    unittest.main()
