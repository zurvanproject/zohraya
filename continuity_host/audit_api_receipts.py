"""Read-only financial and experimental receipt audit for Nasuraya's bounded API pilot.

No HTTP requests, secrets, automatic calls, billing assertions or state mutations.
This report verifies the existing model journal using the existing replay validator.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from continuity_host import model_research as model, research_lab as lab

DAY = timedelta(days=1)


def summarize(state, memory, as_of):
    """Return evidence from verified local snapshots. Never authorize a new call."""
    model.validate(memory)
    if not isinstance(state, dict) or state.get("schema") != "nasuraya-absence-control/1":
        raise ValueError("invalid control state")
    if state.get(model.ANCHOR) != lab.digest(memory):
        raise ValueError("state-to-memory anchor mismatch")

    now = model.stamp(as_of)
    if state.get("last_contact_at") is None:
        raise ValueError("missing operator contact")
    contact = model.stamp(state["last_contact_at"])
    last_claim = (model.stamp(state["last_claimed_at"])
                  if state.get("last_claimed_at") else None)
    if now < contact or (last_claim is not None and now < last_claim):
        raise ValueError("audit time precedes control state")

    entries = memory["entries"]
    if any(model.stamp(entry["at"]) > now for entry in entries):
        raise ValueError("audit time precedes an API reservation")
    reserved = sum(entry["reserved_micro_usd"] for entry in entries)
    recent = sum(entry["reserved_micro_usd"] for entry in entries
                 if now - model.stamp(entry["at"]) < DAY)
    known_estimated = sum(entry["usage"]["estimated_upper_micro_usd"] for entry in entries
                          if entry["status"] == "completed")
    unresolved = [entry["run_id"] for entry in entries if entry["status"] == "pending"]
    details = []
    for entry in entries:
        trial = entry["trial"]
        validation = trial["validation"] if trial is not None else None
        details.append({
            "run_id": entry["run_id"],
            "at": entry["at"],
            "status": entry["status"],
            "feature": entry["proposal"]["feature"] if entry["proposal"] else None,
            "applied": entry["applied"],
            "reserved_micro_usd": entry["reserved_micro_usd"],
            "recorded_usage_estimate_micro_usd": (
                entry["usage"]["estimated_upper_micro_usd"] if entry["usage"] else None),
            "validation_before_errors": validation["before"]["errors"] if validation else None,
            "validation_after_errors": validation["after"]["errors"] if validation else None,
            "validation_sample_size": validation["before"]["total"] if validation else None,
        })
    earliest = max(contact + DAY, (last_claim + DAY) if last_claim else contact + DAY)
    if state.get("enabled") is not True:
        gate = "paused"
    elif state.get("inflight_run_id") is not None or unresolved:
        gate = "unresolved_run"
    elif not model.available(memory):
        gate = "curriculum_complete"
    elif reserved + model.RESERVE > model.LIFETIME_CAP or recent + model.RESERVE > model.DAILY_CAP:
        gate = "financial_cap"
    elif now < earliest:
        gate = "absence_or_daily_gate"
    else:
        gate = "potentially_eligible_not_authorized"

    return {
        "schema": "nasuraya-api-receipt-audit/1",
        "as_of_utc": now.isoformat(),
        "source_scope": "verified repository receipts for synthetic memory research",
        "paid_calls_recorded": sum(e["status"] == "completed" for e in entries),
        "reservations_total_micro_usd": reserved,
        "reservations_last_24h_micro_usd": recent,
        "known_completed_usage_estimate_micro_usd": known_estimated,
        "remaining_pilot_reservations_micro_usd": model.LIFETIME_CAP - reserved,
        "unresolved_run_ids": unresolved,
        "applied_features": [e["proposal"]["feature"] for e in entries
                             if e["status"] == "completed" and e["applied"]],
        "next_gate_window_not_before_utc": earliest.isoformat(),
        "gate_at_audit_time": gate,
        "runs": details,
        "limitations": [
            "Usage is a code-side upper estimate, not an invoice or confirmed charge.",
            "Reservations are retained even if a request failed or was cancelled.",
            "Eligibility is informational; the existing host rechecks all controls.",
            "Validation samples are authored synthetic cases, not independent real-world evidence.",
            "No model was called and no money was spent by this audit."
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--memory", type=Path, required=True)
    parser.add_argument("--as-of", help="explicit ISO-8601 time; defaults to current UTC")
    args = parser.parse_args(argv)
    state = json.loads(args.state.read_text(encoding="utf-8"))
    memory = json.loads(args.memory.read_text(encoding="utf-8"))
    now = args.as_of or datetime.now(timezone.utc).isoformat()
    print(json.dumps(summarize(state, memory, now), ensure_ascii=False,
                     sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
