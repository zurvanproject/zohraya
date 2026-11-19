"""Synthetic contracts; no file, server or model operations."""
import copy
import json
import unittest
from tools import nasu_self_knowledge_lab as lab


def receipt(mode="probe"):
    return {
        "schema": "nasuraya-agent-diagnostics/1",
        "utc": "2026-11-19T06:03:00Z", "mode": mode,
        "units": {"ollama": {"load": "loaded", "active": "active"},
                  "cognition_timer": {"load": "loaded", "active": "active"}},
        "cognition": {"state": "verified_history", "completed": 5,
                      "drafts": 4, "failed": 1, "incomplete": 0},
        "integration": {"state": "ok", "records": 2},
        "executables": {"match": True},
        "probe": {"state": "success"},
    }


def cases(n=20, conf=1.0, correct=True):
    return [{"id": "case-%d" % x, "confidence": conf, "correct": correct,
             "grader": "independent_fixed_rubric"} for x in range(n)]


class Contracts(unittest.TestCase):
    def test_measured_self_model(self):
        cap = lab.self_model(receipt())["capabilities"]
        self.assertEqual(cap, {"inference": "PROBE_PASSED", "research": "OBSERVED", "memory": "OBSERVED"})

    def test_status_alone_cannot_claim_inference(self):
        self.assertEqual(lab.self_model(receipt("status"))["capabilities"]["inference"], "NOT_MEASURED")

    def test_inference_needs_active_model_and_hash(self):
        for name in ("ollama", "hash", "probe"):
            x = receipt()
            if name == "ollama":
                x["units"]["ollama"]["active"] = "inactive"
            elif name == "hash":
                x["executables"]["match"] = False
            else:
                x["probe"]["state"] = "failed"
            self.assertEqual(lab.self_model(x)["capabilities"]["inference"], "NOT_MEASURED")

    def test_failed_or_incoherent_history_not_research(self):
        for v in ("5", True, -1, 3):
            x = receipt()
            x["cognition"]["drafts"] = v
            self.assertEqual(lab.self_model(x)["capabilities"]["research"], "UNKNOWN")

    def test_stopped_timer_is_not_live_research(self):
        x = receipt()
        x["units"]["cognition_timer"]["active"] = "inactive"
        self.assertEqual(lab.self_model(x)["capabilities"]["research"], "UNKNOWN")

    def test_missing_integration_is_not_memory(self):
        x = receipt()
        x["integration"]["state"] = "missing"
        self.assertEqual(lab.self_model(x)["capabilities"]["memory"], "UNKNOWN")

    def test_no_raw_untrusted_fields_in_output(self):
        x = receipt()
        x["private"] = "NEVER_ECHO_SECRET"
        x["probe"]["response"] = "NEVER_ECHO_SECRET"
        self.assertNotIn("NEVER_ECHO_SECRET", json.dumps(lab.self_model(x)))

    def test_bad_schema_or_clock_fails_closed(self):
        x = receipt()
        x["schema"] = "invented"
        with self.assertRaises(ValueError):
            lab.self_model(x)
        x = receipt()
        x["utc"] = "SECRET"
        with self.assertRaises(ValueError):
            lab.self_model(x)

    def test_model_excludes_consciousness_claim(self):
        model = lab.self_model(receipt())
        self.assertIn("no_subjective_awareness_inference", model["limits"])
        self.assertEqual(set(model["capabilities"]), set(lab.CAPABILITIES))

    def test_two_consistent_snapshots_make_only_candidate(self):
        a = lab.self_model(receipt())
        b = copy.deepcopy(a)
        b["utc"] = "2026-11-19T07:03:00Z"
        original = copy.deepcopy([a, b])
        result = lab.consolidation_preview([a, b])
        self.assertTrue(result["originals_retained"])
        self.assertEqual(result["state"], "PROPOSAL_NOT_APPLIED")
        self.assertEqual(result["decisions"]["memory"]["state"], "RETAIN_CANDIDATE")
        self.assertEqual([a, b], original)

    def test_conflicting_measurements_require_review(self):
        a = lab.self_model(receipt("status"))
        b = copy.deepcopy(a)
        b["utc"] = "2026-11-19T07:03:00Z"
        b["capabilities"]["inference"] = "PROBE_PASSED"
        self.assertEqual(lab.consolidation_preview([a, b])["decisions"]["inference"]["state"],
                         "REVIEW_CHANGED_EVIDENCE")

    def test_unknown_does_not_become_memorized_truth(self):
        a = lab.self_model(receipt())
        b = copy.deepcopy(a)
        b["utc"] = "2026-11-19T07:03:00Z"
        b["capabilities"]["research"] = "UNKNOWN"
        self.assertEqual(lab.consolidation_preview([a, b])["decisions"]["research"]["state"], "INSUFFICIENT")

    def test_one_snapshot_not_enough(self):
        a = lab.self_model(receipt())
        self.assertEqual(lab.consolidation_preview([a])["decisions"]["memory"]["state"], "INSUFFICIENT")

    def test_duplicate_or_fake_snapshot_rejected(self):
        a = lab.self_model(receipt())
        with self.assertRaises(ValueError):
            lab.consolidation_preview([a, a])
        a["capabilities"]["claim"] = "OBSERVED"
        with self.assertRaises(ValueError):
            lab.consolidation_preview([a])

    def test_calibration_perfect_correct_and_overconfident_wrong(self):
        correct = lab.calibration_preview(cases())
        wrong = lab.calibration_preview(cases(correct=False))
        self.assertEqual(correct["ece_5bin"], 0)
        self.assertEqual(correct["brier"], 0)
        self.assertEqual(wrong["ece_5bin"], 1)
        self.assertEqual(wrong["brier"], 1)

    def test_short_sample_not_certified(self):
        r = lab.calibration_preview(cases(3))
        self.assertEqual(r["status"], "DESCRIPTIVE_ONLY")
        self.assertFalse(r["subjective_awareness_proven"])

    def test_reject_self_grading_duplicates_and_nan(self):
        for mode in ("self", "duplicate", "nan", "bool"):
            a = cases()
            if mode == "self":
                a[0]["grader"] = "agent_claim"
            elif mode == "duplicate":
                a[1]["id"] = a[0]["id"]
            elif mode == "nan":
                a[0]["confidence"] = float("nan")
            else:
                a[0]["confidence"] = True
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                lab.calibration_preview(a)

    def test_no_weights_or_model_execution(self):
        a = lab.calibration_preview(cases())
        self.assertEqual(a["model_calls"], 0)
        self.assertEqual(a["weight_updates"], 0)


if __name__ == "__main__":
    unittest.main()
