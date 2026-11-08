"""Offline evidence for completed jobs in one public GitHub Actions suite.

Use records collected from GitHub's run and job endpoints. Matching URLs bind
the fields of those records; they cannot authenticate a JSON document handed
to this function. Job IDs distinguish executions, including on the same runner
OS. Jobs can share a runner image, code and infrastructure. On pull requests
GitHub can check out a test merge commit rather than the reported PR head.
"""
import re


def _match(record, expected, subject):
    if not isinstance(record, dict) or any(
        type(record.get(key)) is not type(value) or record[key] != value
        for key, value in expected.items()
    ):
        raise ValueError(f"{subject} does not match the selected GitHub source")


def job_evidence(run, jobs, *, repository, head_sha, run_id, run_attempt,
                 workflow_path, job_names):
    """Normalize raw run/job objects for decide_claim. Select exact job names.

    Inconclusive or out-of-suite jobs contribute no votes. Invalid identifying
    fields on a selected source fail closed. Repeated representations of the
    same GitHub job retain the same origin and receipt. Separate job IDs on
    one OS count as separate jobs, without establishing cross-OS coverage.
    """
    if (not isinstance(repository, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", repository)
            or repository.split("/")[1] in (".", "..")
            or not isinstance(head_sha, str) or not re.fullmatch(r"[a-f0-9]{40}", head_sha)
            or not isinstance(workflow_path, str)
            or not re.fullmatch(r"\.github/workflows/[a-zA-Z0-9_.-]+\.ya?ml", workflow_path)
            or any(type(n) is not int or n < 1 for n in (run_id, run_attempt))):
        raise ValueError("Expected a repository, full SHA, workflow path and positive run IDs")
    if (not isinstance(job_names, (list, tuple, set, frozenset)) or not job_names
            or any(not isinstance(name, str) or not name.strip() for name in job_names)):
        raise ValueError("Select a nonempty collection of exact job names")

    web = f"https://github.com/{repository}"
    api = f"https://api.github.com/repos/{repository}/actions"
    _match(run, {"id": run_id, "run_attempt": run_attempt, "head_sha": head_sha,
                 "path": workflow_path, "status": "completed", "url": f"{api}/runs/{run_id}",
                 "html_url": f"{web}/actions/runs/{run_id}"}, "Workflow run")
    _match(run.get("repository"), {"full_name": repository, "html_url": web,
                                 "private": False}, "Public repository")
    rows = []
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get("name"), str):
            raise ValueError("Malformed GitHub job record")
        if job["name"] not in job_names:
            continue
        job_id = job.get("id")
        if type(job_id) is not int or job_id < 1:
            raise ValueError("Expected a positive GitHub job ID")
        url = f"{api}/jobs/{job_id}"
        _match(job, {"run_id": run_id, "run_attempt": run_attempt, "head_sha": head_sha,
                     "url": url, "html_url": f"{web}/actions/runs/{run_id}/job/{job_id}"},
               "Selected job")
        if job.get("status") != "completed" or job.get("conclusion") not in ("success", "failure"):
            continue
        rows.append({"receipt_id": url, "root_id": f"github:{repository}:run:{run_id}:job:{job_id}",
                     "kind": "execution", "scope": "public", "verified": True,
                     "verdict": "support" if job["conclusion"] == "success" else "oppose"})
    return rows
