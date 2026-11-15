#!/usr/bin/env python3
"""ATMOSPHERE COOL v0.2: bounded, offline, advisory-only resource/research monitor.

No network, model calls, subprocesses, writes, service control, or implicit
authority. A trusted host MUST supply provenance separately, not in sample JSON.
The mode is a suggestion, not a command. It cannot unpause Awake or modify DIOS.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys

SCHEMA = "atmosphere-cool-sample/1"
REPORT_SCHEMA = "atmosphere-cool-advisory/1"
SAMPLE_FIELDS = frozenset({
    "schema", "sampled_at", "cpu_load_per_core", "ram_used_pct", "error_burst_5m",
    "duplicate_ratio_5m", "evidence_age_seconds", "awake_paused",
})
UTC_FORMAT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
MODES = frozenset({"MONITOR", "COOL_ADVISED", "REVIEW_REQUIRED", "OBSERVE_ONLY"})
FRESHNESS_LIMIT_SECONDS = 300
EVIDENCE_STALE_SECONDS = 6 * 3600
MIN_RECOVERY_GAP_SECONDS = 60
PREVIOUS_FIELDS = frozenset({"mode", "healthy_streak", "sampled_at", "sample_digest_sha256"})
SHA256_FORMAT = re.compile(r"[0-9a-f]{64}\Z")


def utc(timestamp: str) -> datetime:
    if not isinstance(timestamp, str) or UTC_FORMAT.fullmatch(timestamp) is None:
        raise ValueError("UTC timestamp with second precision required")
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid UTC timestamp") from exc


def iso(now: datetime) -> str:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("trusted timezone-aware clock required")
    return now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _numeric(value, *, minimum: float, maximum: float, field: str) -> None:
    if value is None:
        return
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError("invalid " + field)


def checked(sample: dict) -> dict:
    if type(sample) is not dict or set(sample) != SAMPLE_FIELDS or sample.get("schema") != SCHEMA:
        raise ValueError("unexpected sample schema or fields")
    if len(json.dumps(sample, ensure_ascii=False, allow_nan=False)) > 4096:
        raise ValueError("oversized sample")
    utc(sample["sampled_at"])
    _numeric(sample["cpu_load_per_core"], minimum=0, maximum=32, field="cpu load")
    _numeric(sample["ram_used_pct"], minimum=0, maximum=100, field="ram use")
    _numeric(sample["duplicate_ratio_5m"], minimum=0, maximum=1, field="duplicate ratio")
    _numeric(sample["evidence_age_seconds"], minimum=0, maximum=365 * 86400,
             field="evidence age")
    errors = sample["error_burst_5m"]
    if errors is not None and (type(errors) is not int or not 0 <= errors <= 1_000_000):
        raise ValueError("invalid error burst")
    if sample["awake_paused"] is not None and type(sample["awake_paused"]) is not bool:
        raise ValueError("awake_paused must be boolean or null")
    return sample.copy()


def _digest(sample: dict) -> str:
    raw = json.dumps(sample, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def next_state(advisory: dict) -> dict:
    """UI-only hysteresis state; not an authentication or execution token."""
    if (type(advisory) is not dict or advisory.get("schema") != REPORT_SCHEMA
            or advisory.get("mode") not in MODES
            or type(advisory.get("healthy_streak")) is not int
            or not 0 <= advisory["healthy_streak"] <= 2
            or not isinstance(advisory.get("sampled_at"), str)
            or not isinstance(advisory.get("sample_digest_sha256"), str)
            or SHA256_FORMAT.fullmatch(advisory["sample_digest_sha256"]) is None):
        raise ValueError("invalid advisory for UI state")
    utc(advisory["sampled_at"])
    return {key: advisory[key] for key in PREVIOUS_FIELDS}


def _check_previous(previous: dict | None) -> None:
    if previous is None:
        return
    if (type(previous) is not dict or set(previous) != PREVIOUS_FIELDS
            or previous["mode"] not in MODES
            or type(previous["healthy_streak"]) is not int
            or not 0 <= previous["healthy_streak"] <= 2
            or type(previous["sample_digest_sha256"]) is not str
            or SHA256_FORMAT.fullmatch(previous["sample_digest_sha256"]) is None):
        raise ValueError("invalid previous advisory state")
    utc(previous["sampled_at"])


def evaluate(sample: dict, *, now: datetime, source_verified: bool = False,
             previous: dict | None = None) -> dict:
    """Pure advisory with timestamp-checked hysteresis and latched review.

    Previous state is a display hint from a trusted host, NOT authority. In
    particular this report cannot authorize restarting any service or DIOS.
    Two recovery credits require observations >=60 seconds apart, not replay.
    """
    s = checked(sample)
    if type(source_verified) is not bool:
        raise ValueError("invalid provenance flag")
    _check_previous(previous)

    wall = utc(iso(now))
    sampled_at = utc(s["sampled_at"])
    delta = (wall - sampled_at).total_seconds()
    prev_time = utc(previous["sampled_at"]) if previous else None
    prev_delta = (sampled_at - prev_time).total_seconds() if previous else None
    same_stamp_conflict = (previous is not None and prev_delta == 0 and
                           previous["sample_digest_sha256"] != _digest(s))
    replay = (previous is not None and prev_delta == 0 and
              previous["sample_digest_sha256"] == _digest(s))
    critical = []
    if s["cpu_load_per_core"] is not None and s["cpu_load_per_core"] >= 2.0:
        critical.append("high-cpu-load")
    if s["ram_used_pct"] is not None and s["ram_used_pct"] >= 92:
        critical.append("critical-memory-pressure")
    if s["error_burst_5m"] is not None and s["error_burst_5m"] >= 6:
        critical.append("error-burst")

    reasons = []
    mode = "MONITOR"
    streak = 0
    if not source_verified:
        reasons = ["source-not-independently-verified"]
        if previous is not None and previous["mode"] == "REVIEW_REQUIRED":
            mode = "REVIEW_REQUIRED"
            reasons.append("previous-review-not-cleared")
        elif previous is not None and previous["mode"] == "COOL_ADVISED":
            mode = "COOL_ADVISED"
            reasons.append("cooling-not-cleared")
        else:
            mode = "OBSERVE_ONLY"
    elif delta < -15:
        mode, reasons = "REVIEW_REQUIRED", ["clock-is-ahead"]
    elif delta > FRESHNESS_LIMIT_SECONDS:
        mode, reasons = "REVIEW_REQUIRED", ["telemetry-stale"]
    elif previous is not None and prev_delta < 0:
        mode, reasons = "REVIEW_REQUIRED", ["sample-clock-regression"]
    elif same_stamp_conflict:
        mode, reasons = "REVIEW_REQUIRED", ["same-timestamp-conflicting-payload"]
    elif critical:
        # Critical resource pressure must remain visible even if Awake is paused
        # or research-only metrics are unavailable.
        mode, reasons = "REVIEW_REQUIRED", critical
    elif previous is not None and previous["mode"] == "REVIEW_REQUIRED":
        mode, reasons = "REVIEW_REQUIRED", ["manual-clearance-needed"]
    elif replay:
        mode = "COOL_ADVISED" if previous["mode"] == "COOL_ADVISED" else "OBSERVE_ONLY"
        streak = previous["healthy_streak"] if mode == "COOL_ADVISED" else 0
        reasons = ["same-sample-no-recovery-credit"]
    elif s["awake_paused"] is True:
        mode, reasons = "OBSERVE_ONLY", ["existing-pause-preserved"]
    elif any(s[field] is None for field in (
            "cpu_load_per_core", "ram_used_pct", "error_burst_5m",
            "duplicate_ratio_5m", "evidence_age_seconds", "awake_paused")):
        mode, reasons = "OBSERVE_ONLY", ["incomplete-evidence"]
    elif s["evidence_age_seconds"] > EVIDENCE_STALE_SECONDS:
        mode, reasons = "REVIEW_REQUIRED", ["research-evidence-too-old"]
    else:
        if s["cpu_load_per_core"] >= .80:
            reasons.append("elevated-cpu-load")
        if s["ram_used_pct"] >= 80:
            reasons.append("elevated-memory-pressure")
        if s["error_burst_5m"] >= 3:
            reasons.append("repeated-errors")
        if s["duplicate_ratio_5m"] >= .60:
            reasons.append("repeated-no-new-evidence")
        if reasons:
            mode = "COOL_ADVISED"
        elif previous is not None and previous["mode"] == "COOL_ADVISED":
            if prev_delta < MIN_RECOVERY_GAP_SECONDS:
                mode, reasons = "COOL_ADVISED", ["awaiting-independent-clean-sample"]
                streak = previous["healthy_streak"]
            else:
                streak = min(previous["healthy_streak"] + 1, 2)
                if streak < 2:
                    mode, reasons = "COOL_ADVISED", ["hysteresis-one-more-clean-sample"]
                else:
                    mode, reasons = "MONITOR", ["two-time-separated-clean-samples"]
        else:
            mode, reasons = "MONITOR", ["within-advisory-thresholds"]

    recommendations = {
        "MONITOR": ["continue-read-only-monitoring"],
        "COOL_ADVISED": ["defer-nonessential-work-after-operator-review",
                         "deduplicate-repeated-research-inputs"],
        "REVIEW_REQUIRED": ["request-human-review-before-any-runtime-change"],
        "OBSERVE_ONLY": ["retain-existing-pause-and-collect-trusted-observations"],
    }
    # Operator-facing suggestions only. Durations are research defaults, not
    # tested scheduling or promised thermal/energy reductions.
    defer = None
    if mode == "COOL_ADVISED":
        defer = (900 if "repeated-no-new-evidence" in reasons and len(reasons) == 1
                 else 600 if "elevated-memory-pressure" in reasons else 300)
    guidance = {
        "nonessential_research_defer_seconds": defer,
        "next_readonly_observation_seconds": {
            "MONITOR": 300, "COOL_ADVISED": 120,
            "REVIEW_REQUIRED": 60, "OBSERVE_ONLY": 300,
        }[mode],
        "requires_operator_before_action": True,
        "changes_services": False,
        "changes_memory": False,
        "claims_temperature_reduction": False,
    }
    return {
        "cooling_plan": guidance,
        "source_verified": source_verified,
        "schema": REPORT_SCHEMA, "mode": mode, "reasons": reasons,
        "recommended_only": recommendations[mode],
        "sample_digest_sha256": _digest(s), "sampled_at": s["sampled_at"],
        "sample_age_seconds": int(delta), "healthy_streak": streak,
        "execution": "NOT_RUN", "authority": "none", "model_calls": 0,
        "network_calls": 0, "writes": 0, "service_actions": 0,
        "allow_unpause": False, "allow_dios_mutation": False,
        "allow_bridge_command": False, "measures_temperature": False,
    }


def evaluate_window(samples: list, *, now: datetime, source_verified: bool = False) -> dict:
    """Assess 1..5 fresh, independently timed samples; no persistent writes.

    This helper prevents recovery via repeated/unchronological observations.
    Host still needs to verify provenance outside sample JSON. Results are
    advisory-only and never establish permission to run a service.
    """
    if type(samples) is not list or not 1 <= len(samples) <= 5:
        raise ValueError("expected 1..5 samples")
    wall = utc(iso(now))
    previous = None
    result = None
    for sample in samples:
        data = checked(sample)
        at = utc(data["sampled_at"])
        if not 0 <= (wall - at).total_seconds() <= FRESHNESS_LIMIT_SECONDS:
            raise ValueError("out-of-window-sample")
        if previous is not None and (
                at - utc(previous["sampled_at"])).total_seconds() < MIN_RECOVERY_GAP_SECONDS:
            raise ValueError("non-independent-timestamps")
        result = evaluate(data, now=wall, source_verified=source_verified,
                          previous=previous)
        previous = next_state(result)
    return {**result, "window_sample_count": len(samples),
            "window_start_at": samples[0]["sampled_at"],
            "window_end_at": samples[-1]["sampled_at"]}


def host_probe(*, now: datetime) -> dict:
    """Passive Linux load/memory sampler; no writes and no process inspection.

    Deliberately leaves research freshness, errors and Awake state UNKNOWN.
    This cannot by itself certify a service safe or ready to run.
    """
    content = Path("/proc/meminfo").read_text(encoding="ascii")
    values = {}
    for line in content.splitlines():
        if ":" not in line:
            continue
        name, rest = line.split(":", 1)
        if name in ("MemTotal", "MemAvailable"):
            values[name] = int(rest.strip().split()[0])
    if not values.get("MemTotal") or "MemAvailable" not in values:
        raise ValueError("Linux memory probe unavailable")
    cores = os.cpu_count()
    if type(cores) is not int or cores < 1:
        raise ValueError("CPU count unavailable")
    ram = 100 * (1 - values["MemAvailable"] / values["MemTotal"])
    load = os.getloadavg()[0] / cores
    return checked({
        "schema": SCHEMA, "sampled_at": iso(now),
        "cpu_load_per_core": round(load, 4), "ram_used_pct": round(ram, 3),
        "error_burst_5m": None, "duplicate_ratio_5m": None,
        "evidence_age_seconds": None, "awake_paused": None,
    })


def demo(*, at: datetime) -> dict:
    return {
        "schema": SCHEMA, "sampled_at": iso(at),
        "cpu_load_per_core": 0.91, "ram_used_pct": 45,
        "error_burst_5m": 0, "duplicate_ratio_5m": .82,
        "evidence_age_seconds": 420, "awake_paused": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="ATMOSPHERE COOL: observational advice only")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--host", action="store_true", help="sample Linux /proc and getloadavg, no writes")
    mode.add_argument("--demo", action="store_true", help="synthetic safe demo")
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    try:
        sample = host_probe(now=now) if args.host else demo(at=now)
        report = evaluate(sample, now=now, source_verified=True)
        if args.demo:
            report["test_fixture"] = True
        print(json.dumps({"snapshot": sample, "advisory": report}, ensure_ascii=False,
                         sort_keys=True, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "not-evaluated", "error": str(exc),
                          "execution": "NOT_RUN"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
