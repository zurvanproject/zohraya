import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from examples.dios_nous.unified import body
from examples.dios_nous.unified.coordinator import run_demo, summary, workload_from_export
from examples.dios_nous.unified.recovery import RecoveryAdvisor


def export(**minimum):
    result = dict(schema=body.EXPORT_SCHEMA, model_id=body.MODEL, clock_domain="simulated_seconds",
                  sampled_at_s=10, revision=1, native_checkpoint_sha256="0" * 64,
                  source_observation_sha256="1" * 64, minimum_state=minimum, finite_stocks={})
    result["sha256"] = hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return result


class CoordinatorTests(unittest.TestCase):
    def test_actual_composition_and_durable_output(self):
        with tempfile.TemporaryDirectory() as root:
            result = run_demo(Path(root), now_utc="2026-11-12T08:00:00Z")
            self.assertEqual(result["body"]["dynamic"]["status"], "unknown_no_observation")
            self.assertEqual(result["workload"]["before_goal_stop"]["state"], "UNKNOWN")
            self.assertEqual(result["workload"]["after_goal_stop"]["state"], "HALTED")
            self.assertEqual(result["cognitive"]["evidence"]["self_correction"]["evidence_review"]["verdict"], "DISSENT")
            self.assertEqual(json.loads((Path(root) / "snapshot.json").read_text(encoding="utf-8")), result)
            self.assertFalse(summary(result)["execution_permitted"])
            for model in result["native_models"]["models"].values():
                self.assertTrue(model["checkpoint_roundtrip_equal"])
            with self.assertRaises(ValueError):
                run_demo(Path(root), now_utc="2026-11-12T08:00:00Z")

    def test_body_pressure_only_changes_workload(self):
        advisor = RecoveryAdvisor()
        result = workload_from_export(advisor, export(sympathetic=.9, fatigue=.8, energy=.1), now_s=10, tick=0)
        self.assertEqual(result["advice"]["state"], "PAUSED")
        self.assertFalse(result["updates_cognitive_evidence"])
        self.assertFalse(result["updates_goal_commitment"])
        stale = workload_from_export(advisor, export(sympathetic=0, fatigue=0, energy=1), now_s=16, tick=1)
        self.assertEqual(stale["advice"]["state"], "UNKNOWN")

    def test_invalid_input_fails_before_state_files(self):
        with tempfile.TemporaryDirectory() as root:
            for args in ({"now_utc": "future-private-canary"},
                         {"now_utc": "2026-11-12T08:00:00Z", "native_export": {"password": "private-canary"}, "now_s": 0}):
                with self.assertRaises(ValueError):
                    run_demo(Path(root), **args)
                self.assertEqual(list(Path(root).iterdir()), [])

    def test_quantization_cannot_promote_near_safe_samples(self):
        for values in (dict(sympathetic=.4001, fatigue=.1, energy=.9),
                       dict(sympathetic=.1, fatigue=.4001, energy=.9),
                       dict(sympathetic=.1, fatigue=.1, energy=.5999)):
            advisor = RecoveryAdvisor()
            result = workload_from_export(advisor, export(**values), now_s=10, tick=0)
            self.assertEqual(result["advice"]["state"], "PAUSED")


if __name__ == "__main__":
    unittest.main()
