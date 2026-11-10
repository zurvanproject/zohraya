"""Public GitHub CI witness audit: five real source-linked records.

This is an offline provenance/status observer, NOT an agent, CI attestor,
retrainer, live-monitor or proof of autonomous behavior. Frozen observations
are verified manually against the GitHub connector and remain fallible.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re

SCHEMA = "nasuraya.public-ci-witness.snapshot.v1"
REPO = "zurvanproject/zohraya"
HEX40 = re.compile(r"\A[0-9a-f]{40}\Z", re.ASCII)

# Independently hand-transcribed from public GitHub Actions connector results
# BEFORE this program was written. These anchors are NOT cryptographic proof.
ANCHORS = {
    42861153251: {
        "workflow": "DIOS NOUS v0.2 equal-information falsification",
        "head_sha": "d745d1e38a7166784babf8c92e10bd90c58bb00a",
        "required": {"dev (ubuntu-24.04)", "dev (windows-2022)", "heldout"},
    },
    42861516737: {
        "workflow": "DIOS NOUS v0.2 equal-information falsification",
        "head_sha": "d78e5272300c28729c54c4a61a52593f297b055d",
        "required": {"dev (ubuntu-24.04)", "dev (windows-2022)", "heldout"},
    },
    42850849443: {
        "workflow": "DIOS NOUS source-aware temporal revision (no network)",
        "head_sha": "fc748536c56aa5023bf7d7e2691ffa70fcb6bf10",
        "required": {"development (ubuntu-24.04)", "development (windows-2022)", "holdout"},
    },
    42846878619: {
        "workflow": "Nasuraya whole-body atlas inventory (offline)",
        "head_sha": "f1c93810abf83bea894ceda2801c3771716c5b30",
        "required": {"inventory (windows-2022)", "inventory (ubuntu-24.04)"},
    },
    42841363043: {
        "workflow": "Nasuraya four-way coordination safety checks",
        "head_sha": "2ad3f35be9a11207d637675931e59de8bcd5fed0",
        "required": {"offline (windows-2022)", "offline (ubuntu-24.04)"},
    },
}
EXPECTED = {
    42861153251: "FAILURE",
    42861516737: "PASSED",
    42850849443: "PASSED",
    42846878619: "PASSED",
    42841363043: "PASSED",
}
VALID_JOB_STATUS = frozenset(("queued", "in_progress", "completed"))
VALID_CONCLUSIONS = frozenset((
    "success", "failure", "skipped", "cancelled", "timed_out", "neutral",
    "action_required", None,
))
VALID_RUN_CONCLUSIONS = frozenset((
    "success", "failure", "cancelled", "skipped", "timed_out", "neutral", None
))


def public_url(run_id: int) -> str:
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("invalid_run_identifier")
    return "https://github.com/" + REPO + "/actions/runs/" + str(run_id)


def canonical_record(record: dict) -> str:
    """Canonical representation of source fields; ignore arbitrary annotations."""
    jobs = record.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("jobs_not_list")
    normalized = []
    for item in jobs:
        if not isinstance(item, dict):
            raise ValueError("bad_job")
        normalized.append({
            "job_id": item.get("job_id"), "name": item.get("name"),
            "status": item.get("status"), "conclusion": item.get("conclusion")
        })
    normalized.sort(key=lambda j: (str(j["job_id"]), str(j["name"])))
    payload = {
        "run_id": record.get("run_id"),
        "workflow": record.get("workflow"),
        "head_sha": record.get("head_sha"),
        "run_status": record.get("run_status"),
        "run_conclusion": record.get("run_conclusion"),
        "jobs": normalized,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def classify_run(record: dict) -> dict:
    """Unknown or mismatched evidence never becomes success."""
    if not isinstance(record, dict):
        raise ValueError("run_not_object")
    run_id = record.get("run_id")
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("invalid_run_id")
    result = {"run_id": run_id, "url": public_url(run_id),
              "evidence_tier": "frozen_public_api_observation"}
    anchor = ANCHORS.get(run_id)
    if not anchor:
        return dict(result, verdict="REVIEW_REQUIRED", reason="unanchored_run")
    if (record.get("workflow") != anchor["workflow"] or
            record.get("head_sha") != anchor["head_sha"] or
            not isinstance(record.get("head_sha"), str) or
            HEX40.fullmatch(record["head_sha"]) is None):
        return dict(result, verdict="REVIEW_REQUIRED", reason="workflow_or_sha_mismatch")
    if record.get("run_status") not in VALID_JOB_STATUS:
        return dict(result, verdict="REVIEW_REQUIRED", reason="invalid_run_status")
    if record.get("run_conclusion") not in VALID_RUN_CONCLUSIONS:
        return dict(result, verdict="REVIEW_REQUIRED", reason="invalid_run_conclusion")
    jobs = record.get("jobs")
    if not isinstance(jobs, list) or not 0 < len(jobs) <= 40:
        return dict(result, verdict="REVIEW_REQUIRED", reason="missing_or_excessive_jobs")
    by_name = {}
    ids = set()
    for item in jobs:
        if not isinstance(item, dict):
            return dict(result, verdict="REVIEW_REQUIRED", reason="invalid_job_shape")
        jid, name = item.get("job_id"), item.get("name")
        if type(jid) is not int or jid <= 0 or not isinstance(name, str):
            return dict(result, verdict="REVIEW_REQUIRED", reason="invalid_job_identity")
        if name in by_name or jid in ids:
            return dict(result, verdict="CONFLICT", reason="duplicate_job_or_id")
        if (item.get("status") not in VALID_JOB_STATUS or
                item.get("conclusion") not in VALID_CONCLUSIONS):
            return dict(result, verdict="REVIEW_REQUIRED", reason="invalid_job_outcome")
        ids.add(jid)
        by_name[name] = item
    # An unknown extra job is not evidence of success for this pinned contract.
    if set(by_name) != anchor["required"]:
        return dict(result, verdict="REVIEW_REQUIRED", reason="required_job_set_mismatch")
    failed = any(
        j["status"] == "completed" and
        j["conclusion"] in ("failure", "timed_out", "cancelled", "action_required")
        for j in by_name.values()
    )
    all_passed = all(
        j["status"] == "completed" and j["conclusion"] == "success"
        for j in by_name.values()
    )
    if failed:
        verdict = "FAILURE"
    elif all_passed and record["run_status"] == "completed":
        verdict = "PASSED"
    else:
        verdict = "INCOMPLETE"
    # Run and job outcomes must agree. A job failure with run "success" must
    # NEVER silently become success; request review for contradictory API data.
    if (verdict == "FAILURE" and record.get("run_conclusion") not in
            ("failure", "cancelled", "timed_out")):
        return dict(result, verdict="REVIEW_REQUIRED", reason="run_job_contradiction")
    if verdict == "PASSED" and record.get("run_conclusion") != "success":
        return dict(result, verdict="REVIEW_REQUIRED", reason="run_job_contradiction")
    if verdict == "INCOMPLETE" and record.get("run_conclusion") == "success":
        return dict(result, verdict="REVIEW_REQUIRED", reason="run_success_but_jobs_incomplete")
    return dict(result, verdict=verdict, reason="reported_required_job_outcomes",
                workflow=anchor["workflow"], head_sha=anchor["head_sha"],
                job_count=len(jobs))


def audit_snapshot(snapshot: dict) -> dict:
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot_not_object")
    if snapshot.get("schema") != SCHEMA or snapshot.get("repository") != REPO:
        raise ValueError("wrong_evidence_source")
    rows = snapshot.get("runs")
    if not isinstance(rows, list) or not 0 < len(rows) <= 30:
        raise ValueError("invalid_runs_collection")
    dedup: dict[int, dict] = {}
    fingerprints: dict[int, str] = {}
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("malformed_record")
        number = item.get("run_id")
        if type(number) is not int or number <= 0:
            raise ValueError("malformed_run_id")
        signature = canonical_record(item)
        if number in dedup:
            if signature != fingerprints[number]:
                dedup[number] = {"run_id": number, "url": public_url(number),
                                 "verdict": "CONFLICT", "reason": "same_run_different_record"}
            continue
        fingerprints[number] = signature
        dedup[number] = classify_run(item)
    ordered = [dedup[number] for number in sorted(dedup)]
    run_by_id = {r["run_id"]: r for r in ordered}
    old = run_by_id.get(42861153251)
    new = run_by_id.get(42861516737)
    transition = "NOT_ESTABLISHED"
    if (old and new and old["verdict"] == "FAILURE" and new["verdict"] == "PASSED"):
        transition = "FAILED_OLD_REVISION_THEN_PASSED_NEW_REVISION"
    report = {
        "schema": "nasuraya.public-ci-witness.audit.v1",
        "source": "frozen_public_github_actions_metadata",
        "not_live_server_evidence": True,
        "not_independent_benchmark": True,
        "not_machine_consciousness_evidence": True,
        "distinct_run_count": len(ordered),
        "job_rows_in_source": sum(len(x["jobs"]) for x in rows),
        "verdict_counts": {label: sum(r["verdict"] == label for r in ordered)
                           for label in ("PASSED", "FAILURE", "INCOMPLETE",
                                         "REVIEW_REQUIRED", "CONFLICT")},
        "v02_transition": transition,
        "runs": ordered,
    }
    return report


def load_and_audit(path: Path) -> dict:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    return audit_snapshot(snapshot)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=(
        Path(__file__).resolve().parents[2] /
        "docs/evidence/public-ci-witness-v01/frozen-public-github-runs.json"
    ))
    args = parser.parse_args()
    result = load_and_audit(args.fixture)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if (result["distinct_run_count"] == 5
                 and result["verdict_counts"]["PASSED"] == 4
                 and result["verdict_counts"]["FAILURE"] == 1
                 and result["v02_transition"] ==
                 "FAILED_OLD_REVISION_THEN_PASSED_NEW_REVISION") else 2


if __name__ == "__main__":
    raise SystemExit(main())
