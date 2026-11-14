"""Source-contract regression using public metadata from archived PR #168."""
import json
import unittest
from pathlib import Path

from examples.nasuraya_research.evidence_lineage import decide_claim
from examples.nasuraya_research.github_job_lineage import job_evidence


class GitHubJobLineageTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).parent / "fixtures" / "github_job_lineage_168.json"
        records = json.loads(path.read_text(encoding="utf-8"))
        self.run, self.jobs = records["run"], records["jobs"]
        self.scope = {
            "repository": "zurvanproject/zohraya",
            "head_sha": "405f7665b8c4372d0a308c0310768a5fcd4b4aa0",
            "run_id": 42475628332, "run_attempt": 1,
            "workflow_path": ".github/workflows/nasuraya-visual-gallery.yml",
            "job_names": {"offline-visual-contract (ubuntu-latest)",
                          "offline-visual-contract (windows-latest)"},
        }

    def decision(self, jobs):
        return decide_claim(job_evidence(self.run, jobs, **self.scope))

    def test_two_actual_job_ids_corroborate_but_two_views_of_one_do_not(self):
        ubuntu, windows = self.jobs
        for jobs, support, decision in (([ubuntu, dict(ubuntu)], 1, "abstain"),
                                        ([ubuntu, windows], 2, "select")):
            result = self.decision(jobs)
            self.assertEqual((support, decision), (result["support"], result["decision"]))

    def test_unrelated_suite_or_inconclusive_job_cannot_be_a_second_success(self):
        ubuntu, windows = self.jobs
        for change in ({"name": "offline-visual-contract-extra (windows-latest)"},
                       {"status": "queued"}, {"conclusion": "cancelled"}, {"conclusion": None}):
            with self.subTest(change=change):
                self.assertEqual("abstain", self.decision([ubuntu, dict(windows, **change)])["decision"])

    def test_failure_polarity_conflicts_with_another_job_success(self):
        ubuntu, windows = self.jobs
        result = self.decision([ubuntu, dict(windows, conclusion="failure")])
        self.assertEqual(("conflicting_evidence", 1, 1),
                         (result["reason"], result["support"], result["oppose"]))

    def test_same_job_with_conflicting_results_is_unresolved(self):
        job = self.jobs[0]
        result = self.decision([job, dict(job, conclusion="failure")])
        self.assertEqual("conflicting_receipt", result["reason"])

    def test_run_is_bound_to_external_scope_and_public_repository(self):
        variants = [
            dict(self.run, head_sha="a" * 40), dict(self.run, id=1),
            dict(self.run, run_attempt=2), dict(self.run, run_attempt=True),
            dict(self.run, path=".github/workflows/unrelated.yml"),
            dict(self.run, url=self.run["url"] + "?alias"),
            dict(self.run, status="in_progress"),
            dict(self.run, repository=dict(self.run["repository"], private=True)),
            dict(self.run, repository=dict(self.run["repository"], html_url="https://example.invalid")),
        ]
        for run in variants:
            with self.subTest(run=run), self.assertRaises(ValueError):
                job_evidence(run, self.jobs, **self.scope)

    def test_job_is_bound_to_its_actual_urls_run_attempt_and_head(self):
        job = self.jobs[0]
        for change in ({"url": job["url"] + "9"}, {"html_url": self.jobs[1]["html_url"]},
                       {"id": True}, {"head_sha": "a" * 40}, {"run_attempt": 2}, {"run_id": 2}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.decision([dict(job, **change)])

    def test_job_count_alone_does_not_establish_os_breadth(self):
        ubuntu, second = self.jobs
        same_os = dict(second, name=ubuntu["name"], labels=ubuntu["labels"])
        self.assertEqual(2, self.decision([ubuntu, same_os])["support"])


if __name__ == "__main__":
    unittest.main()
