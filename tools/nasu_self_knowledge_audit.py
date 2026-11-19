#!/usr/bin/env python3
"""Pure self-knowledge audit of fixed, sanitized Bridge receipts.

No shell, network, model calls, SQLite reads/writes, installs or memory deletion.
This audits reported observations, NOT independently authenticated host facts.
"""
import datetime as dt
import json
import re
from tools import nasu_self_knowledge_lab as base

SCHEMA = "nasuraya-self-knowledge-audit/0.2"
MAX_RECEIPTS = 16
MAX_BYTES = 8192
FENCE = chr(96) * 3


def need(condition, error):
    if not condition:
        raise ValueError(error)


def parse_comment(body):
    need(type(body) is str and len(body.encode("utf-8")) <= MAX_BYTES, "invalid_size")
    lines = body.splitlines()
    need(len(lines) == 7 and lines[3] == FENCE + "text" and
         lines[4] == "exit=0" and lines[6] == FENCE, "invalid_frame")
    need(re.fullmatch(r"nasu-linux-result request_id=[0-9]{6,16}", lines[0]),
         "invalid_request")
    m = re.fullmatch(
        r"action=(agent-status|agent-probe); utc=(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{1,6}\+00:00)",
        lines[1])
    need(m is not None and lines[2] == "host=ubuntu-iran; result:", "invalid_metadata")
    action, stamp = m.groups()
    try:
        received = dt.datetime.fromisoformat(stamp)
        payload = json.loads(lines[5])
    except (ValueError, TypeError):
        raise ValueError("bad_payload") from None
    need(type(payload) is dict, "bad_payload_type")
    model = base.self_model(payload)
    produced = base.timestamp(payload["utc"])
    need(0 <= (received - produced).total_seconds() <= 180, "time_mismatch")
    need(payload["mode"] == ("status" if action == "agent-status" else "probe"),
         "action_mode_mismatch")
    executable = payload["executables"]
    need(type(executable.get("installed")) is str and
         type(executable.get("release")) is str and
         re.fullmatch(r"[0-9a-f]{64}", executable["installed"]) and
         executable["installed"] == executable["release"] and
         executable.get("match") is True, "invalid_executable")
    cognition, integration = payload["cognition"], payload["integration"]
    numbers = [cognition.get(k) for k in ("completed", "drafts", "failed", "incomplete")]
    need(all(base.number(x) for x in numbers) and
         numbers[0] == numbers[1] + numbers[2] and
         base.number(integration.get("records")), "invalid_counts")
    return {
        "request": lines[0].split("=")[1], "utc": payload["utc"],
        "mode": payload["mode"], "digest": executable["installed"],
        "counts": dict(zip(("completed", "drafts", "failed", "incomplete"), numbers),
                       integration=integration["records"]),
        "capabilities": model["capabilities"],
        "provenance": "UNATTESTED_GITHUB_ISSUE_TEXT",
    }


def audit(comments, now):
    need(type(comments) in (list, tuple) and 2 <= len(comments) <= MAX_RECEIPTS,
         "invalid_samples")
    need(isinstance(now, dt.datetime) and now.tzinfo is not None and
         now.utcoffset() == dt.timedelta(0), "utc_now_required")
    rows = [parse_comment(body) for body in comments]
    times = [base.timestamp(x["utc"]) for x in rows]
    need(len(set(x["request"] for x in rows)) == len(rows), "duplicate_request")
    need(all(b > a for a, b in zip(times, times[1:])), "nonmonotonic")
    need(times[-1] <= now, "future_receipt")
    drift = len(set(x["digest"] for x in rows)) != 1
    regression = any(
        b["counts"][key] < a["counts"][key]
        for a, b in zip(rows, rows[1:])
        for key in ("completed", "drafts", "failed", "integration"))
    age = int((now - times[-1]).total_seconds())
    state = ("REVIEW_REQUIRED" if regression or drift else
             "STALE" if age > 7200 else "OBSERVED_WITH_LIMITATIONS")
    probe = any(
        r["mode"] == "probe" and r["capabilities"]["inference"] == "PROBE_PASSED"
        and r["digest"] == rows[-1]["digest"]
        and 0 <= (now - base.timestamp(r["utc"])).total_seconds() <= 1800
        for r in rows)
    return {
        "schema": SCHEMA, "state": state, "samples": len(rows),
        "latest_utc": rows[-1]["utc"], "age_seconds": age,
        "source": "unattested_bridge_comments", "release_changed": drift,
        "counter_regression": regression,
        "increments": {key: rows[-1]["counts"][key] - rows[0]["counts"][key]
                       for key in ("completed", "drafts", "failed", "integration")},
        "capabilities": {
            "inference": "RECENT_FIXED_PROBE" if probe and state == "OBSERVED_WITH_LIMITATIONS"
                         else "NOT_RECENTLY_CONFIRMED",
            "research": rows[-1]["capabilities"]["research"]
                        if state == "OBSERVED_WITH_LIMITATIONS" else "UNKNOWN",
            "memory": rows[-1]["capabilities"]["memory"]
                      if state == "OBSERVED_WITH_LIMITATIONS" else "UNKNOWN"},
        "learning_gain_proven": False, "subjective_awareness_proven": False,
    }


def consolidation_audit(comments):
    need(type(comments) in (list, tuple) and 3 <= len(comments) <= MAX_RECEIPTS,
         "three_snapshots_required")
    rows = [parse_comment(x) for x in comments]
    dates = [base.timestamp(x["utc"]) for x in rows]
    need(all(b > a for a, b in zip(dates, dates[1:])), "bad_order")
    decisions = {}
    for key in base.CAPABILITIES:
        values = [x["capabilities"][key] for x in rows[-3:]]
        if any(v in ("UNKNOWN", "NOT_MEASURED") for v in values):
            status = "INSUFFICIENT"
        elif len(set(values)) > 1:
            status = "REVIEW_CHANGE"
        else:
            status = "CANDIDATE_NOT_ATTESTED"
        decisions[key] = status
    return {"schema": "nasuraya-consolidation/0.2",
            "state": "PROPOSAL_ONLY", "originals_retained": True,
            "writes": 0, "deletions": 0, "decisions": decisions}


def paired_calibration(before, after):
    first, second = base.calibration_preview(before), base.calibration_preview(after)
    need(len(before) == len(after), "different_sample_count")
    a, b = {r["id"]: r for r in before}, {r["id"]: r for r in after}
    need(set(a) == set(b), "unpaired_question_ids")
    better = sum(not a[k]["correct"] and b[k]["correct"] for k in a)
    worse = sum(a[k]["correct"] and not b[k]["correct"] for k in a)
    return {"schema": "nasuraya-paired-calibration/0.2",
            "state": "FIXED_SET_ONLY" if len(a) >= 30 else "DESCRIPTIVE_ONLY",
            "n": len(a), "improved_questions": better, "regressed_questions": worse,
            "accuracy_delta": round(second["accuracy"] - first["accuracy"], 6),
            "brier_delta": round(second["brier"] - first["brier"], 6),
            "ece_delta": round(second["ece_5bin"] - first["ece_5bin"], 6),
            "independent_grading_attested": False,
            "generalized_learning_proven": False, "weights_changed": False}
