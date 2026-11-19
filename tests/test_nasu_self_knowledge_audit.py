"""No-I/O adversarial contracts on synthetic Bridge receipts only."""
import copy
import datetime as dt
import json
import unittest
from tools import nasu_self_knowledge_audit as m

NOW = dt.datetime(2026, 11, 19, 6, 45, 35, tzinfo=dt.timezone.utc)


def receipt(rid=1, hour="06:02:50", mode="status", completed=5,
            drafts=4, failed=1, integration=2, sha="a"*64):
    obj = {"schema": "nasuraya-agent-diagnostics/1",
           "utc": "2026-11-19T" + hour + "Z", "mode": mode,
           "cognition": {"state": "verified_history", "completed": completed,
                         "drafts": drafts, "failed": failed, "incomplete": 0},
           "integration": {"state": "ok", "records": integration},
           "units": {"ollama": {"load": "loaded", "active": "active"},
                     "cognition_timer": {"load": "loaded", "active": "active"}},
           "executables": {"installed": sha, "release": sha, "match": True}}
    if mode == "probe":
        obj["probe"] = {"state": "success"}
    return ("nasu-linux-result request_id=" + str(7000000000 + rid) +
            "\naction=agent-" + mode + "; utc=2026-11-19T" + hour +
            ".200000+00:00\nhost=ubuntu-iran; result:\n" + m.FENCE +
            "text\nexit=0\n" + json.dumps(obj, separators=(",", ":")) +
            "\n" + m.FENCE)


def paired(n=30):
    return [{"id": str(x), "confidence": 0.8, "correct": x != 0,
             "grader": "independent_fixed_rubric"} for x in range(n)]


class AuditContracts(unittest.TestCase):
    def pair(self):
        return [receipt(1, "05:56:44", completed=4, drafts=3, integration=1),
                receipt(2)]

    def test_progress_is_observed_not_equivalent_to_learning(self):
        x = m.audit(self.pair(), NOW)
        self.assertEqual(x["increments"]["completed"], 1)
        self.assertEqual(x["increments"]["integration"], 1)
        self.assertFalse(x["learning_gain_proven"])

    def test_status_does_not_claim_recent_model_proof(self):
        self.assertEqual(m.audit(self.pair(), NOW)["capabilities"]["inference"],
                         "NOT_RECENTLY_CONFIRMED")

    def test_probe_provides_narrow_inference_evidence(self):
        items = self.pair() + [receipt(3, "06:03:00", "probe")]
        fresh_time = NOW - dt.timedelta(minutes=20)
        self.assertEqual(m.audit(items, fresh_time)["capabilities"]["inference"],
                         "RECENT_FIXED_PROBE")
        # A past success is not proof of *current* readiness after 30 minutes.
        self.assertEqual(m.audit(items, NOW)["capabilities"]["inference"],
                         "NOT_RECENTLY_CONFIRMED")

    def test_stale_receipts_cannot_claim_current_running(self):
        x = m.audit(self.pair(), NOW + dt.timedelta(hours=3))
        self.assertEqual(x["state"], "STALE")
        self.assertEqual(x["capabilities"]["memory"], "UNKNOWN")

    def test_rollback_or_counter_regression_flagged(self):
        a = receipt(1, "06:01:00", integration=3)
        b = receipt(2, "06:02:00", integration=2)
        self.assertEqual(m.audit([a, b], NOW)["state"], "REVIEW_REQUIRED")

    def test_binary_digest_changed_requires_review(self):
        items = self.pair()
        items[-1] = receipt(2, sha="b"*64)
        self.assertTrue(m.audit(items, NOW)["release_changed"])

    def test_repeated_request_rejected(self):
        with self.assertRaises(ValueError):
            m.audit([receipt(1, "06:01:00"), receipt(1)], NOW)

    def test_nonmonotonic_time_rejected(self):
        with self.assertRaises(ValueError):
            m.audit(self.pair()[::-1], NOW)

    def test_future_receipt_rejected(self):
        with self.assertRaises(ValueError):
            m.audit(self.pair(), NOW - dt.timedelta(hours=1))

    def test_bad_exit_and_action_mode_rejected(self):
        for msg in (receipt().replace("exit=0", "exit=1"),
                    receipt().replace("action=agent-status", "action=agent-probe")):
            with self.assertRaises(ValueError):
                m.parse_comment(msg)

    def test_untrusted_report_text_does_not_leak(self):
        msg = receipt().replace('"match":true', '"private":"SECRET_CANARY","match":true')
        self.assertNotIn("SECRET_CANARY", json.dumps(m.parse_comment(msg)))

    def test_bad_counts_rejected(self):
        msg = receipt().replace('"completed":5', '"completed":true')
        with self.assertRaises(ValueError):
            m.parse_comment(msg)

    def test_unpinned_executable_rejected(self):
        with self.assertRaises(ValueError):
            m.parse_comment(receipt(sha="unknown"))

    def test_clock_skew_rejected(self):
        msg = receipt().replace("06:02:50.200000", "06:22:50.200000")
        with self.assertRaises(ValueError):
            m.parse_comment(msg)

    def test_requires_three_observations_for_memory(self):
        with self.assertRaises(ValueError):
            m.consolidation_audit(self.pair())

    def test_memory_keeps_originals_no_deletion(self):
        items = self.pair() + [receipt(3, "06:03:00", "probe")]
        out = m.consolidation_audit(items)
        self.assertTrue(out["originals_retained"])
        self.assertEqual(out["writes"], 0)
        self.assertEqual(out["deletions"], 0)
        self.assertEqual(out["decisions"]["research"], "CANDIDATE_NOT_ATTESTED")
        self.assertEqual(out["decisions"]["inference"], "INSUFFICIENT")

    def test_paired_results_are_set_limited(self):
        a = paired()
        b = copy.deepcopy(a)
        b[0]["correct"] = True
        out = m.paired_calibration(a, b)
        self.assertEqual(out["improved_questions"], 1)
        self.assertFalse(out["generalized_learning_proven"])
        self.assertEqual(out["state"], "FIXED_SET_ONLY")

    def test_reject_different_question_ids(self):
        a, b = paired(), paired()
        b[0]["id"] = "different"
        with self.assertRaises(ValueError):
            m.paired_calibration(a, b)

    def test_reject_self_grading(self):
        a, b = paired(), paired()
        b[0]["grader"] = "Qwen"
        with self.assertRaises(ValueError):
            m.paired_calibration(a, b)

    def test_small_set_stays_descriptive(self):
        self.assertEqual(m.paired_calibration(paired(5), paired(5))["state"],
                         "DESCRIPTIVE_ONLY")

    def test_reject_malformed_frame(self):
        with self.assertRaises(ValueError):
            m.parse_comment(receipt().replace("exit=0", "exit=0\nPRIVATE"))

if __name__ == "__main__":
    unittest.main()
