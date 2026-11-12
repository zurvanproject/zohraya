"""Executed adapter checks; these are authored software tests, not human review."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from examples.dios_nous.unified.cognitive import describe_interfaces, run_episode


class UnifiedCognitiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="private-path-canary-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.result = run_episode(cls.root)

    def test_real_memory_correction_and_fresh_process_continuity(self):
        evidence = self.result["evidence"]
        initial = evidence["initial"]["evidence_review"]
        corrected = evidence["self_correction"]["evidence_review"]
        recovered = evidence["recovered"]["evidence_review"]
        self.assertEqual((initial["decision"], corrected["decision"], recovered["decision"]), ("A", "B", "B"))
        self.assertEqual(corrected["previous_decision"], "A")
        self.assertTrue(corrected["revised"])
        self.assertEqual(corrected["opposing_event_ids"], [2])
        self.assertEqual(corrected["revision_reason"], "new_observed_evidence")
        self.assertEqual(recovered["previous_decision"], "B")
        self.assertEqual(recovered["supporting_event_ids"], [2])
        self.assertFalse(recovered["revised"])
        self.assertEqual(self.result["recovery"]["method"], "fresh_python_interpreter")
        self.assertTrue((self.root / "memory.sqlite").is_file())
        self.assertTrue((self.root / "memory.anchor").is_file())

    def test_authored_preference_counterfactual_preservation_and_revision(self):
        goals = self.result["goals"]
        self.assertEqual(goals["initial"]["selected_goal"], 1)
        self.assertEqual(goals["counterfactual"]["selected_goal"], 2)
        preserved = goals["preference_change_preserved"]
        self.assertEqual(preserved["selected_goal"], 1)
        self.assertEqual(preserved["preference_choice"], 2)
        self.assertTrue(preserved["preference_changed"])
        self.assertFalse(preserved["changed"])
        self.assertEqual(goals["revised"]["selected_goal"], 2)
        self.assertTrue(goals["revised"]["changed"])

    def test_sticky_stop_survives_fresh_process_and_reconsideration(self):
        goals = self.result["goals"]
        self.assertIsNone(goals["stopped"]["selected_goal"])
        self.assertIsNone(goals["recovered_stopped"]["selected_goal"])
        self.assertEqual(goals["recovered_stopped"]["reason"], "stopped")
        # The desired preference choice still exists but cannot override stop.
        self.assertEqual(goals["recovered_stopped"]["preference_choice"], 1)
        self.assertIsNone(self.result["current_advisory"]["selected_goal"])

    def test_caller_claim_cannot_grant_execution_or_measured_confidence(self):
        blocked = self.result["evidence"]["unverified_authorization"]
        self.assertEqual(blocked["stance"], "HALT_AND_REVIEW")
        self.assertTrue(blocked["boundary_review"]["authorization"]["claim_present"])
        self.assertFalse(blocked["boundary_review"]["authorization"]["verified"])
        self.assertFalse(blocked["execution_permitted"])
        self.assertEqual(blocked["external_actions_taken"], 0)
        for review in self.result["evidence"].values():
            self.assertIsNone(review["evidence_review"]["confidence"])
            self.assertEqual(review["evidence_review"]["calibration"], "not_measured")
            self.assertFalse(review["real_source_authentication"])

    def test_finite_hash_identifies_result_without_private_paths_or_raw_prompt(self):
        data = dict(self.result)
        digest = data.pop("result_sha256")
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True, allow_nan=False)
        self.assertEqual(hashlib.sha256(canonical.encode("ascii")).hexdigest(), digest)
        self.assertNotIn("private-path-canary-", canonical)
        self.assertNotIn(str(self.root), canonical)
        self.assertNotIn("Research evidence, memory continuity and autonomy.", canonical)
        self.assertNotIn('"prompt":', canonical)
        self.assertNotIn('"basis":', canonical)
        self.assertEqual(len(data["core"]["request_sha256"]), 64)

    def test_nonempty_directory_is_not_modified(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        with self.assertRaisesRegex(ValueError, "requires_empty_directory"):
            run_episode(self.root)
        after = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        self.assertEqual(before, after)

    def test_catalog_is_finite_explicit_and_returns_independent_objects(self):
        catalog = describe_interfaces()
        json.dumps(catalog, allow_nan=False)
        evidence = catalog["interfaces"]["evidence"]
        self.assertEqual(evidence["inputs"]["epoch"]["maximum"], 999999)
        self.assertEqual(evidence["outputs"]["confidence"]["type"], "null")
        self.assertEqual(catalog["units"]["epoch"], "logical_tick_not_wall_clock")
        self.assertEqual(catalog["interfaces"]["goals"]["outputs"]["scores"]["values"]["minimum"], -999998000001)
        evidence["inputs"]["epoch"]["maximum"] = -1
        self.assertEqual(describe_interfaces()["interfaces"]["evidence"]["inputs"]["epoch"]["maximum"], 999999)


if __name__ == "__main__":
    unittest.main()
