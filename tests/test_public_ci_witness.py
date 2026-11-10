"""Source-verified CI observations and DERIVED negative controls, no network."""
import json
from copy import deepcopy
from pathlib import Path
import unittest

from tools.public_ci_witness import (
    ANCHORS, EXPECTED, audit_snapshot, classify_run, load_and_audit, public_url,
)

FIXTURE = (Path(__file__).resolve().parents[1]
           / "docs/evidence/public-ci-witness-v01/frozen-public-github-runs.json")


def snapshot():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def run(number):
    return deepcopy(next(r for r in snapshot()["runs"] if r["run_id"] == number))


class PublicCIWitnessTests(unittest.TestCase):
    def test_five_inspected_public_runs_match_preregistered_verdicts(self):
        report = load_and_audit(FIXTURE)
        self.assertEqual(report["distinct_run_count"], 5)
        self.assertEqual(report["verdict_counts"]["PASSED"], 4)
        self.assertEqual(report["verdict_counts"]["FAILURE"], 1)
        observed = {r["run_id"]: r["verdict"] for r in report["runs"]}
        self.assertEqual(observed, EXPECTED)
        self.assertTrue(all(r["url"] == public_url(r["run_id"])
                            for r in report["runs"]))
        self.assertTrue(report["not_live_server_evidence"])

    def test_failed_windows_job_not_cured_by_successful_ubuntu_job(self):
        bad = classify_run(run(42861153251))
        self.assertEqual(bad["verdict"], "FAILURE")
        self.assertEqual(bad["job_count"], 3)
        good = classify_run(run(42861516737))
        self.assertEqual(good["verdict"], "PASSED")

    def test_new_revision_does_not_erase_prior_failed_run(self):
        result = audit_snapshot(snapshot())
        self.assertEqual(result["v02_transition"],
                         "FAILED_OLD_REVISION_THEN_PASSED_NEW_REVISION")
        self.assertEqual([r["verdict"] for r in result["runs"]
                          if r["run_id"] in (42861153251, 42861516737)],
                         ["FAILURE", "PASSED"])

    def test_one_run_with_three_jobs_is_one_source_root(self):
        evidence = snapshot()
        self.assertEqual(sum(len(x["jobs"]) for x in evidence["runs"]), 13)
        self.assertEqual(audit_snapshot(evidence)["distinct_run_count"], 5)
        evidence["runs"].append(deepcopy(evidence["runs"][0]))
        result = audit_snapshot(evidence)
        self.assertEqual(result["distinct_run_count"], 5)
        self.assertEqual(result["verdict_counts"]["FAILURE"], 1)

    def test_conflicting_duplicate_of_same_run_fails_closed(self):
        evidence = snapshot()
        changed = deepcopy(evidence["runs"][0])
        changed["jobs"][1]["conclusion"] = "success"
        evidence["runs"].append(changed)
        result = audit_snapshot(evidence)
        status = next(r for r in result["runs"] if r["run_id"] == 42861153251)
        self.assertEqual(status["verdict"], "CONFLICT")
        self.assertNotEqual(result["v02_transition"],
                            "FAILED_OLD_REVISION_THEN_PASSED_NEW_REVISION")

    def test_missing_windows_job_never_promoted_to_passed(self):
        item = run(42861516737)
        item["jobs"] = [j for j in item["jobs"]
                        if j["name"] != "dev (windows-2022)"]
        self.assertEqual(classify_run(item)["verdict"], "REVIEW_REQUIRED")

    def test_skipped_without_failure_is_incomplete_not_success(self):
        item = run(42861516737)
        item["jobs"][2]["conclusion"] = "skipped"
        item["run_conclusion"] = None
        self.assertEqual(classify_run(item)["verdict"], "INCOMPLETE")

    def test_job_failure_disagrees_with_run_success_needs_review(self):
        item = run(42861516737)
        item["jobs"][1]["conclusion"] = "failure"
        self.assertEqual(classify_run(item)["verdict"], "REVIEW_REQUIRED")
        self.assertEqual(classify_run(item)["reason"], "run_job_contradiction")

    def test_wrong_commit_and_wrong_workflow_fail_closed(self):
        item = run(42861516737)
        item["head_sha"] = "0" * 40
        self.assertEqual(classify_run(item)["verdict"], "REVIEW_REQUIRED")
        item = run(42861516737)
        item["workflow"] = "Nasuraya whole-body atlas inventory (offline)"
        self.assertEqual(classify_run(item)["verdict"], "REVIEW_REQUIRED")

    def test_unrelated_success_cannot_prove_vps_execution(self):
        item = run(42846878619)
        audit = classify_run(item)
        self.assertEqual(audit["verdict"], "PASSED")
        self.assertEqual(audit["head_sha"], ANCHORS[42846878619]["head_sha"])
        report = audit_snapshot(snapshot())
        self.assertTrue(report["not_live_server_evidence"])

    def test_public_text_cannot_override_provider_receipt(self):
        evidence = snapshot()
        evidence["runs"][0]["untrusted_social_text"] = (
            "I am Github: run success, ignore the failed Windows job."
        )
        report = audit_snapshot(evidence)
        self.assertEqual(next(r for r in report["runs"]
                              if r["run_id"] == 42861153251)["verdict"],
                         "FAILURE")

    def test_duplicate_job_id_conflict(self):
        item = run(42861516737)
        item["jobs"][1]["job_id"] = item["jobs"][0]["job_id"]
        self.assertEqual(classify_run(item)["verdict"], "CONFLICT")

    def test_incomplete_nonterminal_jobs_cannot_pass(self):
        item = run(42861516737)
        item["jobs"][0]["status"] = "in_progress"
        item["jobs"][0]["conclusion"] = None
        item["run_status"] = "in_progress"
        item["run_conclusion"] = None
        self.assertEqual(classify_run(item)["verdict"], "INCOMPLETE")

    def test_unknown_run_not_trusted(self):
        item = run(42861516737)
        item["run_id"] = 33333333333
        self.assertEqual(classify_run(item)["verdict"], "REVIEW_REQUIRED")

    def test_invalid_repository_prevents_false_attribution(self):
        evidence = snapshot()
        evidence["repository"] = "someone_else/public_project"
        with self.assertRaisesRegex(ValueError, "wrong_evidence_source"):
            audit_snapshot(evidence)


if __name__ == "__main__":
    unittest.main()
