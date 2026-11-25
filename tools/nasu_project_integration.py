#!/usr/bin/env python3
"""Assemble a read-only project view from explicitly collected JSON evidence.

No network, model, service, shell or database operation exists in this module.
The input is an observation bundle, never a command. GitHub owner comments are
linked reports, not independently signed proof of execution. Public Moltbook
access cannot establish that the Ubuntu process polls Moltbook.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit, parse_qs

INPUT_SCHEMA = "nasuraya-project-evidence/1"
SCHEMA = "nasuraya-project-integration/1"
REPO = "zurvanproject/zohraya"
OWNER = "zurvanproject"
BASE = "https://github.com/" + REPO
ISSUE = BASE + "/issues/212"
LEGACY_ISSUE = BASE + "/issues/149"
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_COMMENTS = 3000
FRESH_SECONDS = {"github": 86400, "server": 7200, "profile": 86400,
                 "feed": 3600, "profile_activity": 259200,
                 "cognitive_cycle": 43200, "integration_cycle": 7200}
SHA = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
REQUEST = re.compile(r"nasu-linux: (agent-status|agent-probe|repo|research-status)\Z")
RESULT_ID = re.compile(r"\Anasu-linux-result request_id=([1-9][0-9]*)\n")
RESULT = re.compile(
    r"\Anasu-linux-result request_id=([1-9][0-9]*)\n"
    r"action=(agent-status|agent-probe); utc=([^\n]+)\n"
    r"host=ubuntu-iran; result:\n```text\nexit=0\n(\{[^\n]*\})\n```\s*\Z"
)
AUX_RESULT = re.compile(
    r"\Anasu-linux-result request_id=([1-9][0-9]*)\n"
    r"action=(repo|research-status); utc=([^\n]+)\n"
    r"host=ubuntu-iran; result:\n```text\n([^`]+)\n```\s*\Z"
)
# This pair is established by the pinned targeted updater, not by caller text.
KNOWN_INSTALLED = "797669845a680dfc408482c16513e254267323597fff49e3af458e315eee4fe5"
KNOWN_RELEASE = "011d2b485958e16e34acd1c8c8744dc42adf92a9ef21f8a9d570e3b6cef15742"
KNOWN_UPDATE_SOURCE = (BASE + "/blob/f8bbe739c9b72d7d45a6ba2e9c823771f160d512/"
                       "tools/apply_nasu_cognition_292.py")
UNITS = frozenset(("ollama", "cognition", "cognition_timer", "integration", "integration_timer"))
LOAD = frozenset(("loaded", "not-found", "masked", "error", "bad-setting", "stub", "merged", "unknown"))
ACTIVE = frozenset(("active", "inactive", "failed", "activating", "deactivating", "reloading", "maintenance", "refreshing", "unknown"))
SUB = frozenset(("running", "exited", "dead", "failed", "waiting", "elapsed", "start", "start-pre", "start-post", "auto-restart", "stop", "stop-sigterm", "stop-sigkill", "reload", "unknown"))
RESULTS = frozenset(("success", "exit-code", "timeout", "signal", "core-dump", "watchdog", "start-limit-hit", "resources", "protocol", "dependency", "oom-kill", "exec-condition", "assert", "unknown"))
STATES = frozenset(("missing", "invalid", "empty", "incomplete", "verified_history"))
MODELS = frozenset(("UNVERIFIED_DRAFT", "model_unavailable", "source_unavailable", "test_unavailable"))
FAILURES = frozenset(("response_too_large", "invalid_response_json", "invalid_envelope", "incomplete_generation", "invalid_draft_json", "invalid_draft", "incomplete_http_response", "timeout", "transport_error", "connection_refused", "http_error"))
RUN_STATUS = frozenset(("queued", "in_progress", "completed", "waiting", "requested", "pending"))
CONCLUSIONS = frozenset(("success", "failure", "neutral", "cancelled", "skipped", "timed_out", "action_required", "stale", "startup_failure"))


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _integer(value):
    _require(type(value) is int and 0 <= value <= 2**63 - 1, "invalid_counter")
    return value


def _time(value):
    _require(isinstance(value, str) and len(value) <= 40 and
             re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value),
             "invalid_utc_time")
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _stamp(value):
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _now(value):
    value = value or dt.datetime.now(dt.timezone.utc)
    _require(isinstance(value, dt.datetime) and value.tzinfo is not None and
             value.utcoffset() == dt.timedelta(0), "UTC_now_required")
    return value


def _age(stamp, now, limit):
    if stamp is None:
        return {"state": "unknown", "max_age_seconds": limit}
    moment = _time(stamp)
    age = int((now - moment).total_seconds())
    return {"state": "future" if moment > now else "fresh" if age <= limit else "stale",
            "observed_at_utc": _stamp(moment), "age_seconds": age, "max_age_seconds": limit}


def _slot(value, *, hourly=False):
    pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:00Z" if hourly else r"\d{4}-\d{2}-\d{2}T\d{2}"
    _require(isinstance(value, str) and re.fullmatch(pattern, value), "invalid_cycle_time")
    stamp = value[:-1] + ":00Z" if hourly else value + ":00:00Z"
    parsed = _time(stamp)
    _require(hourly or parsed.hour in (0, 6, 12, 18), "invalid_cognitive_slot")
    return stamp


def _finding(priority, action, *urls):
    return {"priority": priority, "action": action, "evidence_urls": list(dict.fromkeys(u for u in urls if u))}



# Advisory routing only. Titles are untrusted metadata, never executable input
# or evidence of code ownership, compatibility, completion, or safe deployment.
DEVELOPMENT_LANES = (
    ("security", r"\b(?:atmosphere|security|adversarial|signed|authorization|defen[cs]e|perimeter|integrity|veto)\b|امنیت|امضای", ("examples/dios_nous/audit.py", "tools/atmosphere_defensive_ritual_sim.py")),
    ("infrastructure", r"\b(?:vps|ubuntu|windows|bridge|ollama|qwen|backup|restore|migration|deployment|scheduler|cron|offline|server|api|host|receipt|parallelism)\b|سرور|پشتیبان|استقرار", ("tools/nasu_project_integration.py", "tools/nasuraya_linux_bridge.py", "tools/nasu_autonomous_cognition.py")),
    ("ritual_and_learning", r"\b(?:ritual|daoist|kavakeb|setar|masnavi|shams|gates of fire|practice|prayer|fourth way|zurvan|learning|apprenticeship)\b|ریچوال|آیین|کواکب|یادگیری|شاهنامه", ("tools/nasu_feedback_learning.py", "tools/nasu_kavakeb_three_gazes.py", "tools/nasu_evidence_to_experiment.py")),
    ("affect", r"\b(?:affect\w*|emotion\w*|curiosity|frustration|desire|motivation\w*|valuation|appraisal|preference\w*|libido|calm)\b|عاطف|احساس|انگیزه", ("examples/nasuraya_body_loop/affect_audit.py", "runtimes/tadash_body/retained_extensions/nasuraya_affective_layer_v01.py")),
    ("memory", r"\b(?:memory|awake|continuity|journal|ledger|replay|recall|dialogue|temporal|source-attributed|checkpoint)\b|حافظه|پیوستگی|دفتر", ("continuity_host/host.py", "tools/nasu_unified_status.py", "tools/nasu_integration_rehearsal.py")),
    ("body", r"\b(?:body|native|pelvis|pudendal|spinal|physic\w*|motor|motion|contact|walk\w*|posture|balance|foot|feet|tail|cardio\w*|respirat\w*|anatomy|muscle|proprioception|neuro\w*|standing|sleep)\b|بدن|کالبد|آناتومی|حرکت", ("examples/nasuraya_body_loop/host.py", "runtimes/tadash_body/persistent_embodiment_v1.py")),
    ("identity_and_media", r"\b(?:genome|genotype|phenotype|visual|image|portrait|identity|letter|video|audio|resonan|taraneh)\b|ژنوم|هویت|تصویر|چهره", ("examples/nasuraya_genome/traits.py", "examples/nasuraya_body_mirror/build.py")),
    ("social", r"\b(?:moltbook|social|fourway|community)\b|مولت", ("tools/nasu_collect_project_status.py", "tools/nasu_project_integration.py")),
    ("cognition", r"\b(?:dios|cogniti\w*|self-model|self-knowledge|goal\w*|agent\w*|research|forecast\w*|prediction\w*|decision\w*|world-model|policy|consciousness|metacogniti\w*|experiment\w*|rolyel)\b|شناخت|تصمیم|پژوهش", ("examples/dios_nous/cognition.py", "examples/dios_nous/integration.py", "tools/nasu_evidence_to_experiment.py")),
)
DEVELOPMENT_GATES = (
    "review_exact_diff_and_assign_canonical_owner",
    "compare_overlapping_work_and_preserve_negative_evidence",
    "verify_interfaces_and_cross_component_regressions",
    "review_current_head_required_checks_and_authorization",
    "record_rollback_and_separate_deployment_receipt_if_applicable",
)


def _development_queue(prs, titles, current_checks, complete, freshness):
    """A complete projection of accepted open PRs, not an integration verdict."""
    destinations = {lane: list(paths) for lane, _, paths in DEVELOPMENT_LANES}
    destinations["unclassified"] = ["tools/nasu_project_integration.py"]
    groups = {lane: [] for lane in destinations}
    queue = []
    checks_by_head = {}
    for check in current_checks:
        checks_by_head.setdefault(check["head_sha"], []).append(check)
    for pr in sorted(prs, key=lambda row: row["number"]):
        title = titles.get(pr["number"], "")
        candidates = [lane for lane, pattern, _ in DEVELOPMENT_LANES
                      if re.search(pattern, title, flags=re.IGNORECASE)]
        lane = candidates[0] if candidates else "unclassified"
        groups[lane].append(pr["number"])
        checks = checks_by_head.get(pr["head_sha"], [])
        if any(c["conclusion"] in {"failure", "timed_out", "action_required", "startup_failure"} for c in checks):
            ci = "failure_observed"
        elif any(c["status"] != "completed" for c in checks):
            ci = "pending_observed"
        elif any(c["conclusion"] == "success" for c in checks):
            ci = "success_observed_not_all_required"
        else:
            ci = "unknown_or_no_success_observed"
        queue.append({
            "number": pr["number"], "head_sha": pr["head_sha"],
            "source_url": pr["source_url"], "draft": pr["draft"],
            "provisional_lane": lane, "candidate_lanes": candidates,
            "routing_basis": "title_metadata_only",
            "ci_observation": ci, "state": "review_required",
            "merge_or_deploy_authorized": False,
        })
    return {
        "state": "review_required",
        "observed_count": len(queue),
        "collection_complete": complete,
        "collection_freshness": freshness,
        "atomic_snapshot": False,
        "groups": groups,
        "candidate_destinations": destinations,
        "multi_lane_numbers": [p["number"] for p in queue if len(p["candidate_lanes"]) > 1],
        "unclassified_numbers": groups["unclassified"],
        "closure_requirements": list(DEVELOPMENT_GATES),
        "queue": queue,
        "limitations": [
            "routing_is_advisory_and_titles_do_not_prove_code_overlap",
            "observed_ci_is_bounded_and_does_not_prove_all_required_checks",
            "no_pr_is_merged_closed_or_deployed_by_this_report",
        ],
    }


def _github(data, now):
    if data is None:
        return {"state": "missing_evidence"}, [_finding(2, "collect_current_github_evidence", BASE)]
    _require(isinstance(data, dict) and data.get("repository") == REPO, "wrong_github_repository")
    freshness = _age(data.get("retrieved_at_utc"), now, FRESH_SECONDS["github"])
    main = data.get("main", {})
    _require(isinstance(main, dict) and isinstance(main.get("sha"), str) and SHA.fullmatch(main["sha"]), "invalid_main_sha")
    _require(main.get("html_url") == BASE + "/commit/" + main["sha"], "invalid_main_source")
    rows = data.get("pull_requests", [])
    runs = data.get("workflow_runs", [])
    _require(isinstance(rows, list) and len(rows) <= 1000 and isinstance(runs, list) and len(runs) <= 2000, "github_collection_limit")
    prs, rejected_prs, seen = [], 0, set()
    titles = {}
    for row in rows:
        try:
            _require(isinstance(row, dict) and type(row.get("number")) is int and row["number"] > 0 and row["number"] not in seen, "invalid_pr")
            _require(row.get("state") == "open" and type(row.get("draft")) is bool, "invalid_pr_state")
            sha = row.get("head", {}).get("sha")
            _require(isinstance(sha, str) and SHA.fullmatch(sha), "invalid_pr_sha")
            url = BASE + "/pull/" + str(row["number"])
            _require(row.get("html_url") == url, "invalid_pr_source")
            updated = _time(row["updated_at"])
            _require(updated <= now, "future_pr")
            seen.add(row["number"])
            title = row.get("title")
            if isinstance(title, str):
                titles[row["number"]] = title[:240]
            prs.append({"number": row["number"], "draft": row["draft"], "head_sha": sha,
                        "updated_at_utc": _stamp(updated), "source_url": url})
        except (ValueError, TypeError, KeyError, AttributeError):
            rejected_prs += 1
    checks, rejected_runs, seen = [], 0, set()
    for row in runs:
        try:
            _require(isinstance(row, dict) and type(row.get("id")) is int and row["id"] > 0 and row["id"] not in seen, "invalid_run")
            _require(row.get("status") in RUN_STATUS and (row.get("conclusion") is None or row.get("conclusion") in CONCLUSIONS), "invalid_run_state")
            _require(row["status"] != "completed" or row.get("conclusion") in CONCLUSIONS, "missing_conclusion")
            _require(row["status"] == "completed" or row.get("conclusion") is None, "premature_conclusion")
            sha = row.get("head_sha")
            _require(isinstance(sha, str) and SHA.fullmatch(sha), "invalid_run_sha")
            url = BASE + "/actions/runs/" + str(row["id"])
            _require(row.get("html_url") == url, "invalid_run_source")
            stamp = _time(row["updated_at"])
            _require(stamp <= now, "future_run")
            name = row.get("name")
            _require(isinstance(name, str) and 0 < len(name) <= 160 and all(c.isprintable() for c in name), "invalid_run_name")
            workflow_id = row.get("workflow_id")
            _require(workflow_id is None or type(workflow_id) is int and workflow_id > 0, "invalid_workflow_id")
            seen.add(row["id"])
            checks.append({"id": row["id"], "name": name, "head_sha": sha, "status": row["status"],
                           "conclusion": row.get("conclusion"), "source_url": url,
                           "updated_at_utc": _stamp(stamp), "workflow_id": workflow_id})
        except (ValueError, TypeError, KeyError, AttributeError):
            rejected_runs += 1
    # A display name is not workflow identity. Without a numeric ID, preserve
    # every observed run so a similarly named success cannot hide a failure.
    latest = {}
    for row in sorted(checks, key=lambda r: (r["updated_at_utc"], r["id"])):
        identity = ("workflow", row["workflow_id"]) if row["workflow_id"] is not None else ("unidentified_run", row["id"])
        latest[(row["head_sha"], identity)] = row
    heads = {main["sha"], *(p["head_sha"] for p in prs)}
    current = [row for row in latest.values() if row["head_sha"] in heads]
    failed = [r for r in current if r["conclusion"] in {"failure", "timed_out", "action_required", "startup_failure"}]
    findings = [_finding(1, "review_current_head_check_failure", r["source_url"]) for r in failed]
    if freshness["state"] != "fresh":
        findings.append(_finding(1, "refresh_github_observation", main["html_url"]))
    if rejected_prs or rejected_runs:
        findings.append(_finding(2, "review_rejected_github_evidence", BASE))
    return {"state": "observed", "freshness": freshness, "main": {"sha": main["sha"], "source_url": main["html_url"]},
            "open_prs_observed": len(prs), "draft_prs_observed": sum(p["draft"] for p in prs),
            "development_queue": _development_queue(prs, titles, current,
                data.get("pull_requests_complete") is True and not rejected_prs, freshness["state"]),
            "pr_collection_complete": data.get("pull_requests_complete") is True and not rejected_prs,
            "ready_pr_numbers": sorted(p["number"] for p in prs if not p["draft"]),
            "recent_prs": sorted(prs, key=lambda r: (r["updated_at_utc"], r["number"]), reverse=True)[:20],
            "workflow_runs_observed": len(checks), "workflow_collection_scope": "provided_bounded_sample",
            "current_head_checks": sorted(current, key=lambda r: (r["updated_at_utc"], r["id"]), reverse=True),
            "current_head_failures": len(failed), "rejected_prs": rejected_prs, "rejected_runs": rejected_runs,
            "all_required_checks_verified": False}, findings


def _comment(row, now, *, issue_url=ISSUE):
    _require(isinstance(row, dict) and type(row.get("id")) is int and row["id"] > 0, "invalid_comment")
    _require(row.get("html_url") == issue_url + "#issuecomment-" + str(row["id"]), "wrong_comment_source")
    _require(isinstance(row.get("user"), dict) and row["user"].get("login") == OWNER, "untrusted_actor")
    _require(isinstance(row.get("body"), str) and len(row["body"]) <= 20000, "invalid_comment_body")
    created = _time(row["created_at"])
    updated = _time(row.get("updated_at", row["created_at"]))
    _require(updated == created and created <= now, "edited_or_future_comment")
    return created


def _diagnostics(value, action, now):
    _require(isinstance(value, dict) and value.get("schema") == "nasuraya-agent-diagnostics/1", "unknown_diagnostics_schema")
    required = {"schema", "utc", "mode", "units", "cognition", "executables", "integration"}
    _require(set(value) == required | ({"probe"} if action == "agent-probe" else set()), "unknown_diagnostics_fields")
    _require(value["mode"] == ("probe" if action == "agent-probe" else "status"), "diagnostics_mode_mismatch")
    stamp = _time(value["utc"])
    _require(stamp <= now, "future_diagnostics")
    units = value["units"]
    _require(isinstance(units, dict) and set(units) == UNITS, "unknown_units")
    safe_units = {}
    for name, row in units.items():
        _require(isinstance(row, dict), "invalid_unit")
        if row == {"state": "unavailable"}:
            safe_units[name] = dict(row)
            continue
        keys = {"load", "active", "sub", "next", "last"} if name.endswith("_timer") else {"load", "active", "sub", "result", "exit"}
        _require(set(row) == keys and row["load"] in LOAD and row["active"] in ACTIVE and row["sub"] in SUB, "invalid_unit_state")
        if name.endswith("_timer"):
            for key in ("next", "last"):
                if row[key] is not None:
                    _time(row[key])
            if row["last"] is not None:
                _require(_time(row["last"]) <= stamp, "future_timer_last_trigger")
        else:
            _require(row["result"] in RESULTS and (row["exit"] is None or type(row["exit"]) is int and 0 <= row["exit"] <= 255), "invalid_unit_result")
        safe_units[name] = dict(row)
    cognition = value["cognition"]
    _require(isinstance(cognition, dict) and cognition.get("state") in STATES, "invalid_cognition")
    if cognition["state"] in {"missing", "invalid"}:
        _require(set(cognition) == {"state"}, "invalid_cognition_fields")
    else:
        _require(set(cognition) == {"state", "completed", "incomplete", "drafts", "failed", "latest", "last_successful_slot"}, "invalid_cognition_fields")
        for key in ("completed", "incomplete", "drafts", "failed"):
            _integer(cognition[key])
        _require(cognition["drafts"] + cognition["failed"] == cognition["completed"], "inconsistent_cognitive_counts")
        expected_state = ("incomplete" if cognition["incomplete"] else
                          "verified_history" if cognition["completed"] else "empty")
        _require(cognition["state"] == expected_state, "inconsistent_cognitive_state")
        latest = cognition["latest"]
        _require((latest is None) == (cognition["completed"] == 0), "inconsistent_latest_cycle")
        if latest is not None:
            _require(isinstance(latest, dict) and {"slot", "model"} <= set(latest) <= {"slot", "model", "failure_reason"} and latest["model"] in MODELS, "invalid_latest_cycle")
            _require(_time(_slot(latest["slot"])) <= stamp, "future_cycle")
            if "failure_reason" in latest:
                _require(latest["model"] == "model_unavailable" and latest["failure_reason"] in FAILURES, "unknown_failure_reason")
        if cognition["last_successful_slot"] is not None:
            _require(_time(_slot(cognition["last_successful_slot"])) <= stamp, "future_successful_cycle")
        _require((cognition["last_successful_slot"] is not None) == (cognition["drafts"] > 0),
                 "inconsistent_successful_cycle_count")
        if latest is not None:
            if latest["model"] == "UNVERIFIED_DRAFT":
                _require(cognition["drafts"] > 0 and cognition["last_successful_slot"] == latest["slot"],
                         "inconsistent_latest_success")
            else:
                _require(cognition["failed"] > 0 and (cognition["last_successful_slot"] is None or
                         _time(_slot(cognition["last_successful_slot"])) < _time(_slot(latest["slot"]))),
                         "inconsistent_latest_failure")
    integration = value["integration"]
    _require(isinstance(integration, dict) and integration.get("state") in STATES | {"ok", "unknown", "missing_module"}, "invalid_integration")
    _require(set(integration) <= {"state", "records", "hour"}, "unknown_integration_fields")
    if "records" in integration:
        _integer(integration["records"])
    if "hour" in integration:
        _require(_time(_slot(integration["hour"], hourly=True)) <= stamp, "future_integration_cycle")
    executable = value["executables"]
    _require(isinstance(executable, dict) and set(executable) == {"installed", "release", "match"}, "invalid_executable_metadata")
    for key in ("installed", "release"):
        _require(isinstance(executable[key], str) and (SHA256.fullmatch(executable[key]) or executable[key] in {"missing", "invalid"}), "invalid_executable_hash")
    comparable = bool(SHA256.fullmatch(executable["installed"]) and SHA256.fullmatch(executable["release"]))
    expected = executable["installed"] == executable["release"] if comparable else None
    _require(executable["match"] is expected, "inconsistent_hash_match")
    result = {"utc": _stamp(stamp), "mode": value["mode"], "units": safe_units,
              "cognition": cognition, "integration": integration, "executables": dict(executable)}
    if action == "agent-probe":
        probe = value["probe"]
        _require(isinstance(probe, dict) and probe.get("state") in {"success", "failed"}, "invalid_probe")
        _require(set(probe) == ({"state", "sha256"} if probe["state"] == "success" else {"state"}), "invalid_probe_fields")
        if probe["state"] == "success":
            _require(isinstance(probe["sha256"], str) and SHA256.fullmatch(probe["sha256"]), "invalid_probe_hash")
        result["probe"] = dict(probe)
    return result


def _deployment(executable, declarations):
    result = {"installed_sha256": executable["installed"], "release_sha256": executable["release"],
              "raw_match": executable["match"], "relationship": "unverified"}
    if executable["match"] is True:
        result["relationship"] = "same_reported_bytes"
    elif executable["match"] is False:
        result["relationship"] = "different_versions_unexplained"
        if isinstance(declarations, list) and len(declarations) <= 20:
            for record in declarations:
                if (isinstance(record, dict) and record.get("installed_sha256") == KNOWN_INSTALLED == executable["installed"] and
                        record.get("release_sha256") == KNOWN_RELEASE == executable["release"] and
                        record.get("source_url") == KNOWN_UPDATE_SOURCE and record.get("label") == "targeted_cognition_update"):
                    result.update(relationship="recognized_targeted_update_against_frozen_release",
                                  recognition_source_url=KNOWN_UPDATE_SOURCE,
                                  recognition_scope="pinned_updater_metadata_not_independent_host_attestation")
                    break
    return result


def _auxiliary_receipts(requests, receipts, duplicate_ids, now):
    """Project two fixed read-only replies without interpreting commands."""
    out = {}
    for action in ("repo", "research-status"):
        candidates = [r for r in requests.values() if r["action"] == action]
        if not candidates:
            out[action] = {"state": "not_provided"}
            continue
        request = max(candidates, key=lambda r: (r["created"], r["id"]))
        replies = receipts.get(request["id"], [])
        request_url = ISSUE + "#issuecomment-" + str(request["id"])
        result = {"state": "awaiting_receipt", "request_url": request_url}
        out[action] = result
        if request["id"] in duplicate_ids or len(replies) > 1:
            result["state"] = "ambiguous_receipts"
            continue
        if not replies:
            continue
        row, created = replies[0]
        result["receipt_url"] = ISSUE + "#issuecomment-" + str(row["id"])
        try:
            match = AUX_RESULT.fullmatch(row["body"])
            _require(row["id"] not in duplicate_ids and match is not None and
                     int(match[1]) == request["id"] and match[2] == action, "invalid_auxiliary_link")
            stamp = _time(match[3])
            # GitHub comment timestamps have second precision; the Bridge keeps
            # microseconds. The two observations may differ within that second.
            _require(request["created"] <= stamp < created + dt.timedelta(seconds=1) and stamp <= now,
                     "invalid_auxiliary_time")
            lines = match[4].splitlines()
            _require(lines and lines[0] == "exit=0", "auxiliary_command_failed")
            if action == "repo":
                _require(len(lines) >= 4 and re.fullmatch(r"## main\.\.\.origin/main(?: \[(?:ahead|behind) [1-9][0-9]*(?:, (?:ahead|behind) [1-9][0-9]*)?\])?", lines[1]) and
                         lines[-2] == "exit=0" and re.fullmatch(r"[0-9a-f]{7,40}", lines[-1]), "invalid_repo_receipt")
                _require(all(re.fullmatch(r"[ MADRCU?!]{2} .{1,500}", line) for line in lines[2:-2]), "unknown_worktree_status")
                result.update(state="observed", branch="main", reported_revision=lines[-1],
                              revision_is_abbreviated=len(lines[-1]) < 40,
                              worktree_changes_observed=len(lines[2:-2]))
            else:
                _require(len(lines) == 2, "invalid_research_receipt")
                history = json.loads(lines[1])
                _require(isinstance(history, dict) and set(history) == {"schema", "state", "completed", "correct", "errors", "last_sha", "task_issue", "total", "valid"} and
                         history["schema"] == "nasuraya-bridge-research/1" and history["state"] in {"completed", "running", "stopped", "failed"} and history["task_issue"] == 290,
                         "unknown_research_status")
                for key in ("completed", "correct", "errors", "total", "valid"):
                    _integer(history[key])
                _require(history["correct"] <= history["valid"] <= history["completed"] <= history["total"] and
                         history["errors"] <= history["completed"] and isinstance(history["last_sha"], str) and SHA256.fullmatch(history["last_sha"]), "invalid_research_counts")
                result.update(state="reported_history_only", history=history,
                              execution_time_known=False, new_execution_proven=False)
            result["receipt_freshness"] = _age(_stamp(stamp), now, FRESH_SECONDS["server"])
        except (ValueError, TypeError, KeyError, AttributeError):
            result["state"] = "invalid_receipt"
    return out


def _server(data, now):
    if data is None:
        return {"state": "missing_evidence", "health": "unknown"}, [_finding(1, "collect_current_server_receipt", ISSUE)]
    _require(isinstance(data, dict) and data.get("issue_url") == ISSUE, "wrong_server_issue")
    collection_age = _age(data.get("retrieved_at_utc"), now, FRESH_SECONDS["server"])
    rows = data.get("comments")
    _require(isinstance(rows, list) and len(rows) <= MAX_COMMENTS, "invalid_comment_collection")
    requests, receipts, rejected, duplicate_ids = {}, {}, 0, set()
    seen = set()
    for row in rows:
        try:
            created = _comment(row, now)
            if row["id"] in seen:
                duplicate_ids.add(row["id"])
                continue
            seen.add(row["id"])
            body = row["body"]
            match = REQUEST.fullmatch(body.splitlines()[0]) if body.splitlines() else None
            if match:
                requests[row["id"]] = {"id": row["id"], "action": match.group(1), "created": created}
            result = RESULT_ID.match(body)
            if result:
                receipts.setdefault(int(result.group(1)), []).append((row, created))
        except (ValueError, TypeError, KeyError, AttributeError):
            rejected += 1
    out = {"state": "no_diagnostic_request", "health": "unknown", "collection_freshness": collection_age,
           "source_url": ISSUE, "rejected_comments": rejected,
           "evidence_kind": "linked_owner_comments_not_independent_execution_attestation"}
    out["related_receipts"] = _auxiliary_receipts(requests, receipts, duplicate_ids, now)
    diagnostics_requests = [r for r in requests.values() if r["action"] in {"agent-status", "agent-probe"}]
    if not diagnostics_requests:
        return out, [_finding(1, "collect_current_server_receipt", ISSUE)]
    request = max(diagnostics_requests, key=lambda r: (r["created"], r["id"]))
    request_url = ISSUE + "#issuecomment-" + str(request["id"])
    out["latest_request"] = {"id": request["id"], "action": request["action"], "source_url": request_url,
                             "created_at_utc": _stamp(request["created"])}
    replies = receipts.get(request["id"], [])
    if request["id"] in duplicate_ids or len(replies) > 1:
        out["state"] = "ambiguous_receipts"
        return out, [_finding(1, "review_ambiguous_server_receipts", request_url)]
    if not replies:
        out["state"] = "awaiting_receipt"
        return out, [_finding(1, "await_current_server_receipt", request_url)]
    row, created = replies[0]
    receipt_url = ISSUE + "#issuecomment-" + str(row["id"])
    out["receipt_url"] = receipt_url
    try:
        _require(row["id"] not in duplicate_ids and created >= request["created"], "receipt_before_request_or_duplicate")
        match = RESULT.fullmatch(row["body"])
        _require(match is not None and int(match[1]) == request["id"] and match[2] == request["action"], "unmatched_or_malformed_receipt")
        receipt_time = _time(match[3])
        # GitHub created_at truncates fractions that the Bridge UTC preserves.
        _require(request["created"] <= receipt_time < created + dt.timedelta(seconds=1) and receipt_time <= now,
                 "invalid_receipt_time")
        value = _diagnostics(json.loads(match[4]), request["action"], now)
        diagnostic_time = _time(value["utc"])
        _require(diagnostic_time + dt.timedelta(seconds=1) > request["created"] and
                 diagnostic_time <= receipt_time and (receipt_time - diagnostic_time).total_seconds() <= 300,
                 "diagnostic_receipt_time_mismatch")
    except (ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError):
        out["state"] = "invalid_receipt"
        return out, [_finding(1, "review_invalid_server_receipt", receipt_url)]
    age = _age(value["utc"], now, FRESH_SECONDS["server"])
    out.update(state="observed", freshness=age, diagnostics=value,
               deployment=_deployment(value["executables"], data.get("recognized_deployments")))
    findings = []
    cognition = value["cognition"]
    if cognition["state"] in {"invalid", "incomplete"} or cognition.get("incomplete", 0):
        findings.append(_finding(1, "inspect_invalid_or_incomplete_cognitive_receipts", receipt_url))
    elif cognition["state"] in {"missing", "empty"}:
        findings.append(_finding(1, "inspect_missing_cognitive_history", receipt_url))
    latest = cognition.get("latest")
    if latest and latest["model"] != "UNVERIFIED_DRAFT":
        findings.append(_finding(1, "inspect_latest_model_or_input_failure", receipt_url))
    if latest:
        out["cognitive_cycle_freshness"] = _age(_slot(latest["slot"]), now, FRESH_SECONDS["cognitive_cycle"])
        if out["cognitive_cycle_freshness"]["state"] != "fresh":
            findings.append(_finding(1, "inspect_stale_cognitive_cycle", receipt_url))
    integration = value["integration"]
    if integration["state"] not in {"ok", "verified_history"}:
        findings.append(_finding(1, "inspect_integration_journal", receipt_url))
    out["integration_cycle_freshness"] = _age(_slot(integration["hour"], hourly=True) if "hour" in integration else None, now, FRESH_SECONDS["integration_cycle"])
    if out["integration_cycle_freshness"]["state"] != "fresh":
        findings.append(_finding(1, "inspect_stale_or_unknown_integration_cycle", receipt_url))
    for name, unit in value["units"].items():
        expected_active = name in {"ollama", "cognition_timer", "integration_timer"}
        if (unit.get("state") == "unavailable" or unit.get("load") != "loaded" or
                expected_active and unit.get("active") != "active" or
                unit.get("active") == "failed" or unit.get("result", "success") not in {"success"} or
                unit.get("exit", 0) not in {0, None}):
            findings.append(_finding(1, "inspect_service_" + name, receipt_url))
    if value.get("probe", {}).get("state") == "failed":
        findings.append(_finding(1, "inspect_failed_local_model_probe", receipt_url))
    if age["state"] != "fresh" or collection_age["state"] != "fresh":
        findings.append(_finding(1, "refresh_server_observation", receipt_url))
    if out["deployment"]["relationship"] in {"unverified", "different_versions_unexplained"}:
        findings.append(_finding(2, "review_executable_version_provenance", receipt_url))
    out["health"] = "attention_required" if findings else "observed_checks_passed"
    return out, findings


def _molt_url(value, kind):
    _require(isinstance(value, str) and len(value) <= 500, "invalid_moltbook_source")
    parsed = urlsplit(value)
    _require(parsed.scheme == "https" and parsed.netloc in {"www.moltbook.com", "moltbook.com"} and not parsed.fragment, "invalid_moltbook_host")
    if kind == "profile":
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        _require(parsed.path == "/api/v1/agents/profile" and set(query) == {"name"} and
                 len(query["name"]) == 1 and query["name"][0].lower() == "nasuraya", "wrong_profile_source")
        return "https://www.moltbook.com/api/v1/agents/profile?name=nasuraya"
    elif kind == "feed":
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        _require(parsed.path == "/api/v1/posts" and set(query) == {"sort", "limit"} and
                 query["sort"] == ["new"] and len(query["limit"]) == 1 and
                 re.fullmatch(r"[1-9][0-9]{0,2}", query["limit"][0]) and int(query["limit"][0]) <= 100,
                 "invalid_feed_source")
        return "https://www.moltbook.com/api/v1/posts?sort=new&limit=" + query["limit"][0]
    else:
        _require(re.fullmatch(r"/(?:api/v1/posts|post)/" + UUID, parsed.path) and not parsed.query, "invalid_post_source")
    return value


def _moltbook(data, now):
    if data is None:
        return {"state": "missing_evidence", "runtime_linkage": "UNKNOWN"}, [_finding(2, "collect_public_moltbook_observation")]
    _require(isinstance(data, dict) and data.get("schema") == "nasuraya-public-moltbook-evidence/1" and data.get("expected_profile_name") == "nasuraya", "unknown_moltbook_schema")
    profile = data.get("public_profile", {})
    agent = profile.get("agent", {})
    _require(isinstance(agent, dict) and agent.get("name") == "nasuraya", "wrong_moltbook_profile")
    source = _molt_url(profile.get("source_url"), "profile")
    acquired = _age(profile.get("acquired_at_utc"), now, FRESH_SECONDS["profile"])
    activity = _age(agent.get("last_active"), now, FRESH_SECONDS["profile_activity"])
    safe = {"name": "nasuraya"}
    for key in ("posts_count", "comments_count", "follower_count", "following_count"):
        if key in agent:
            safe[key] = _integer(agent[key])
    for key in ("is_claimed", "is_active"):
        if key in agent:
            _require(type(agent[key]) is bool, "invalid_profile_flag")
            safe[key] = agent[key]
    out = {"state": "observed", "profile": {"source_url": source, "observation_freshness": acquired,
            "activity_freshness": activity, "platform_fields": safe},
           "runtime_linkage": "UNKNOWN", "authenticated_server_poll_verified": False,
           "public_profile_and_feed_do_not_prove_runtime_linkage": True}
    findings = []
    if acquired["state"] != "fresh":
        findings.append(_finding(2, "refresh_moltbook_profile_observation", source))
    if activity["state"] != "fresh":
        findings.append(_finding(2, "review_stale_or_unknown_moltbook_profile_activity", source))
    feed = data.get("feed")
    if feed is None:
        out["feed"] = {"state": "missing_evidence"}
    else:
        _require(isinstance(feed, dict), "invalid_feed")
        feed_url = _molt_url(feed.get("source_url"), "feed")
        feed_age = _age(feed.get("acquired_at_utc"), now, FRESH_SECONDS["feed"])
        items = feed.get("items", [])
        _require(isinstance(items, list) and len(items) <= 100, "feed_limit")
        by_id, rejected, duplicates, ambiguous = {}, 0, 0, set()
        for row in items:
            try:
                _require(isinstance(row, dict) and isinstance(row.get("id"), str) and re.fullmatch(UUID, row["id"]), "invalid_post")
                url = _molt_url(row.get("source_url"), "post")
                _require(url.endswith("/" + row["id"]), "post_source_mismatch")
                stamp = _time(row["created_at"])
                _require(stamp <= now and stamp <= _time(feed["acquired_at_utc"]), "future_feed_post")
                observation = {"id": row["id"], "created_at_utc": stamp.isoformat(), "source_url": url}
                if row["id"] in by_id:
                    duplicates += 1
                    if observation != by_id[row["id"]]:
                        ambiguous.add(row["id"])
                else:
                    by_id[row["id"]] = observation
            except (ValueError, TypeError, KeyError):
                rejected += 1
        posts = [row for key, row in by_id.items() if key not in ambiguous]
        newest = max((p["created_at_utc"] for p in posts), default=None)
        out["feed"] = {"state": "ambiguous_evidence" if ambiguous else "observed", "source_url": feed_url, "observation_freshness": feed_age,
                       "newest_post_freshness": _age(newest, now, FRESH_SECONDS["feed"]),
                       "posts_observed": len(posts), "rejected_posts": rejected,
                       "fetched_items": len(items), "unique_posts": len(by_id),
                       "duplicate_items": duplicates, "ambiguous_posts": len(ambiguous),
                       "newly_seen": None, "newly_seen_basis": "requires_persistent_prior_observation",
                       "coverage": "bounded_sample_not_complete_history", "posts": posts}
        if feed_age["state"] != "fresh" or rejected or ambiguous:
            findings.append(_finding(2, "refresh_or_review_public_feed_evidence", feed_url))
    findings.append(_finding(2, "verify_moltbook_runtime_link_with_separate_server_evidence", source, ISSUE))
    return out, findings


def _legacy(data, now):
    if data is None:
        return {"state": "not_provided", "scope": "historical_windows_only"}, []
    _require(isinstance(data, dict) and data.get("issue_url") == LEGACY_ISSUE, "wrong_legacy_issue")
    rows = data.get("comments", [])
    _require(isinstance(rows, list) and len(rows) <= MAX_COMMENTS, "legacy_collection_limit")
    accepted = []
    for row in rows:
        try:
            stamp = _comment(row, now, issue_url=LEGACY_ISSUE)
            if row["body"].startswith("Nasuraya Bridge v2 result;"):
                accepted.append({"source_url": LEGACY_ISSUE + "#issuecomment-" + str(row["id"]), "reported_at_utc": _stamp(stamp)})
        except (ValueError, KeyError, TypeError):
            continue
    return {"state": "historical_metadata_only", "scope": "historical_windows_only",
            "source_url": LEGACY_ISSUE, "receipt_metadata": accepted[-10:],
            "validates_current_ubuntu_or_moltbook": False}, []


def assemble(bundle, *, now=None):
    """Pure projection: return sanitized observations and unexecuted next steps."""
    now = _now(now)
    _require(isinstance(bundle, dict) and bundle.get("schema") == INPUT_SCHEMA, "unknown_evidence_bundle")
    output, findings = {}, []
    for name, reader in (("github", _github), ("server", _server), ("moltbook", _moltbook), ("legacy", _legacy)):
        try:
            component, actions = reader(bundle.get(name), now)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            component = {"state": "invalid_evidence"}
            actions = [_finding(1, "review_invalid_" + name + "_evidence")]
        output[name] = component
        findings.extend(actions)
    unique = {(f["priority"], f["action"], tuple(f["evidence_urls"])): f for f in findings}
    repo_receipt = output["server"].get("related_receipts", {}).get("repo", {})
    github_head = output["github"].get("main", {}).get("sha")
    if repo_receipt.get("state") == "observed" and github_head:
        repo_receipt["matches_observed_github_head_prefix"] = github_head.startswith(repo_receipt["reported_revision"])
        repo_receipt["full_checkout_revision_matches_observed_main"] = not repo_receipt["revision_is_abbreviated"] and repo_receipt["matches_observed_github_head_prefix"]
    actions = sorted(unique.values(), key=lambda r: (r["priority"], r["action"]))
    return {"schema": SCHEMA, "generated_at_utc": _stamp(now), "mode": "OBSERVE_PLAN_ONLY",
            "components": output, "next_steps": actions, "external_actions_taken": 0,
            "model_calls": 0, "runtime_linkage": "PARTIAL_NOT_PROVEN",
            "freshness_policy_seconds": dict(FRESH_SECONDS),
            "limitations": ["provided_observations_are_not_independent_attestations",
                            "no_atomic_snapshot_across_sources",
                            "bounded_workflow_sample_does_not_prove_all_required_checks",
                            "public_moltbook_access_does_not_prove_server_polling",
                            "plans_are_not_executed_and_existing_runtime_journals_are_unchanged"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-file", type=Path, required=True)
    parser.add_argument("--now", help="UTC observation time for reproducible audits")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    try:
        path = args.from_file
        _require(not path.is_symlink() and path.is_file() and path.stat().st_size <= MAX_INPUT_BYTES, "unsafe_or_oversized_input")
        with path.open("rb") as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
        _require(len(raw) <= MAX_INPUT_BYTES, "oversized_input")
        result = assemble(json.loads(raw), now=_time(args.now) if args.now else None)
    except (OSError, ValueError, TypeError, RecursionError):
        result = {"schema": SCHEMA, "state": "invalid_evidence_bundle", "mode": "OBSERVE_PLAN_ONLY", "external_actions_taken": 0}
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2 if args.pretty else None))
    return 1 if result.get("state") == "invalid_evidence_bundle" else 0


if __name__ == "__main__":
    sys.exit(main())
