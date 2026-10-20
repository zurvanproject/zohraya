"""Offline trace consistency audit. Reads data; never executes a customer's code."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

MAX_BYTES = 2_000_000
MAX_EVENTS = 5000
KINDS = {"start", "finish", "fail", "effect"}
ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")
FIXES = {
    "duplicate_start": "Use a durable unique request claim before starting work.",
    "request_reused": "Bind request IDs to one attempt; reconcile before retrying.",
    "orphan_terminal": "Record the start before its terminal event; check export completeness.",
    "duplicate_terminal": "Make terminal publication idempotent and retain original outcomes.",
    "duplicate_effect": "Reconcile the external effect using its idempotency key before retrying.",
    "effect_outside_run": "Persist an active run before recording effects; check event order.",
    "unresolved_run": "Investigate the worker and effect outcome before retrying.",
    "budget_exceeded": "Enforce a budget before admission, with reserved capacity for in-flight work.",
}


def parse(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError("input exceeds 2 MB")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("input must be UTF-8") from None
    events = []
    previous = None
    for line, item in enumerate(text.splitlines(), 1):
        if not item.strip():
            continue
        if len(events) >= MAX_EVENTS:
            raise ValueError("input exceeds 5000 events")
        try:
            e = json.loads(item)
            required = {"at", "kind", "run_id", "request_id", "cost_minor"}
            if not isinstance(e, dict) or set(e) - (required | {"effect_id"}) or required - set(e):
                raise ValueError()
            if e["kind"] not in KINDS:
                raise ValueError()
            for key in ("run_id", "request_id"):
                if not isinstance(e[key], str) or not ID.fullmatch(e[key]):
                    raise ValueError()
            if type(e["cost_minor"]) is not int or not 0 <= e["cost_minor"] <= 10**12:
                raise ValueError()
            if e["kind"] == "effect":
                if not isinstance(e.get("effect_id"), str) or not ID.fullmatch(e["effect_id"]):
                    raise ValueError()
            elif "effect_id" in e:
                raise ValueError()
            at = datetime.fromisoformat(e["at"].replace("Z", "+00:00"))
            if at.tzinfo is None or at.utcoffset() is None:
                raise ValueError()
            at = at.astimezone(timezone.utc)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            # Do not echo customer input, identifiers or parser exception snippets.
            raise ValueError(f"invalid event schema at line {line}") from None
        if previous is not None and at < previous:
            raise ValueError(f"out-of-order timestamp at line {line}")
        previous = at
        events.append((line, e))
    if not events:
        raise ValueError("input has no events")
    return events


def audit(raw, budget_minor, currency):
    if type(budget_minor) is not int or budget_minor < 0:
        raise ValueError("budget must be a nonnegative integer")
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("currency must be a three-letter uppercase code")
    events = parse(raw)
    active, requests, started, terminals, effects = {}, {}, set(), set(), {}
    findings, total = [], 0
    over_budget = False

    def flag(code, line, prior=None):
        row = {"code": code, "line": line, "recommendation": FIXES[code]}
        if prior is not None:
            row["related_line"] = prior
        findings.append(row)

    for line, e in events:
        run, request, kind = e["run_id"], e["request_id"], e["kind"]
        total += e["cost_minor"]
        if total > budget_minor and not over_budget:
            flag("budget_exceeded", line)
            over_budget = True
        if kind == "start":
            if run in started:
                flag("duplicate_start", line)
            else:
                started.add(run)
                active[run] = (line, request)
            if request in requests:
                flag("request_reused", line, requests[request])
            else:
                requests[request] = line
        elif kind in {"finish", "fail"}:
            if run in terminals:
                flag("duplicate_terminal", line)
            elif run not in active or active[run][1] != request:
                flag("orphan_terminal", line)
            else:
                del active[run]
                terminals.add(run)
        else:
            effect = e["effect_id"]
            if run not in active or active[run][1] != request:
                flag("effect_outside_run", line)
            if effect in effects:
                flag("duplicate_effect", line, effects[effect])
            else:
                effects[effect] = line
    for line, _ in active.values():
        flag("unresolved_run", line)
    return {
        "schema": "nasuraya-trace-audit/1",
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "event_count": len(events),
        "result": "review_required" if findings else "no_listed_anomaly_observed",
        "cost_basis": "caller-reported incremental amounts; not verified billing",
        "currency": currency, "reported_cost_minor": total, "budget_minor": budget_minor,
        "counts": dict(sorted(Counter(f["code"] for f in findings).items())),
        "findings": findings,
        "limitations": [
            "Trace-only consistency review; no code execution, crash injection or external verification.",
            "Missing starts/ends may reflect a partial export rather than a runtime defect.",
            "Repeated effect records are candidates for investigation, not proof of repeated payment.",
            "Input must use one currency and incremental costs, not cumulative billing totals.",
            "No findings does not prove safety, exactly-once execution or complete logging.",
        ],
    }


def markdown(report):
    lines = ["# NASURAYA Offline Trace Audit", "", f"Result: **{report['result']}**",
             f"Events: {report['event_count']}",
             f"Input SHA-256: `{report['input_sha256']}`", "",
             f"Reported cost: {report['reported_cost_minor']} minor units {report['currency']}; "
             f"budget: {report['budget_minor']}.", "", report["cost_basis"], "",
             "| Finding | Line | Related line | Suggested action |",
             "| --- | ---: | ---: | --- |"]
    for f in report["findings"]:
        lines.append(f"| {f['code']} | {f['line']} | {f.get('related_line', '')} | {f['recommendation']} |")
    if not report["findings"]:
        lines.append("| No listed anomaly observed | | | Review the limitations below. |")
    lines += ["", "## Limitations", ""] + ["- " + x for x in report["limitations"]]
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", type=Path)
    p.add_argument("--budget-minor", type=int, required=True)
    p.add_argument("--currency", required=True)
    p.add_argument("--format", choices=("json", "markdown"), default="json")
    args = p.parse_args()
    try:
        if not args.input.is_file():
            raise ValueError("input must be a regular local file")
        with args.input.open("rb") as f:
            raw = f.read(MAX_BYTES + 1)
        report = audit(raw, args.budget_minor, args.currency)
    except (OSError, ValueError):
        print("Audit failed: check the schema, timestamps, file size and parameters.", file=sys.stderr)
        return 2
    print(markdown(report) if args.format == "markdown" else json.dumps(report, indent=2), end="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
