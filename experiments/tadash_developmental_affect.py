"""Advisory developmental affect from Tadash motor evidence, with durable cold recovery.

Not a subjective feeling, sexuality engine, or autonomous actuator. A single audited
motor report can inform a bounded curiosity/comfort/frustration heuristic; synthetic
counterfactuals stay labelled synthetic. No external calls, no live body mutation.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

SCHEMA = "tadash-developmental-affect/1"
AUDIT_SCHEMA = "tadash-motor-learning-independent-audit/1"
MAX_EVENTS = 16
STATE_FIELDS = ("curiosity", "calm", "frustration", "confidence")
ALLOWED_ORIGINS = ("verified_previous_motor_audit", "synthetic_fixture")
ALLOWED_KINDS = ("progress", "failed_attempt", "rest", "unsafe")
EXPECTED_MOTOR_RUN = 41484110737


def compact(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(obj):
    return hashlib.sha256(compact(obj).encode("utf-8")).hexdigest()


def finite01(x, name):
    if type(x) not in (int, float) or not math.isfinite(x) or not 0. <= x <= 1.:
        raise ValueError(f"{name} must be finite 0..1")
    return float(x)


def verify_audit(path):
    """Scope check on a prior independently reviewed report, not authentication."""
    audit = json.loads(Path(path).read_text(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    if audit.get("schema") != AUDIT_SCHEMA or audit.get("workflow_run_id") != EXPECTED_MOTOR_RUN:
        raise ValueError("Wrong motor audit provenance")
    if audit.get("all_conditions_met") is not True or audit.get("native_trials") != 19:
        raise ValueError("Missing previous motor criteria")
    if audit.get("holdout_better_cases") != 8 or audit.get("holdout_pairs") != 8:
        raise ValueError("Incomplete held-out result")
    if audit.get("deployment") != "none; draft PR unmerged; model weights unchanged":
        raise ValueError("Unexpected source scope")
    measured = finite01(audit.get("holdout_relative_improvement"), "holdout improvement")
    if measured < .20:
        raise ValueError("Insufficient audited motor improvement")
    if audit.get("model_source_commit") != "c6bac77802a7fab9178fb00eed28e3c4410b9482":
        raise ValueError("Different mechanical source")
    return {"audit_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            "motor_improvement": measured, "motor_run_id": EXPECTED_MOTOR_RUN,
            "source_claim": "prior_aggregate_audit_not_raw_trial_reexecution"}


@dataclass
class State:
    curiosity: float = .30
    calm: float = .65
    frustration: float = .05
    confidence: float = .25


def check_state(values):
    if type(values) is not dict or set(values) != set(STATE_FIELDS):
        raise ValueError("Incomplete affect state")
    for key, value in values.items():
        finite01(value, key)


def checked_event(event):
    expected = {"id", "origin", "kind", "novelty", "evidence_digest"}
    if type(event) is not dict or set(event) != expected:
        raise ValueError("Event fields must be exact")
    if type(event["id"]) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", event["id"]):
        raise ValueError("Invalid event id")
    if event["origin"] not in ALLOWED_ORIGINS or event["kind"] not in ALLOWED_KINDS:
        raise ValueError("Unknown evidence origin or kind")
    finite01(event["novelty"], "novelty")
    if not isinstance(event["evidence_digest"], str) or not re.fullmatch("[0-9a-f]{64}", event["evidence_digest"]):
        raise ValueError("Missing evidence digest")
    if event["origin"] == "verified_previous_motor_audit" and event["kind"] != "progress":
        raise ValueError("Audited motor report only supports progress event")
    if event["origin"] == "synthetic_fixture" and event["kind"] == "progress":
        raise ValueError("No synthetic success promoted as audited motor progress")
    return event


def change(state, event):
    """Normalized fictional affect proxies with bounded, inspectable transitions."""
    check_state(state)
    checked_event(event)
    s = dict(state)
    kind = event["kind"]
    if kind == "progress":
        s["curiosity"] += .16 * event["novelty"] + .08 * (1 - s["curiosity"])
        s["confidence"] += .25 * (1 - s["confidence"])
        s["calm"] += .06 * (1 - s["calm"])
        s["frustration"] *= .65
    elif kind == "failed_attempt":
        s["frustration"] += .36 * (1 - s["frustration"])
        s["confidence"] *= .63
        s["curiosity"] *= .72
        s["calm"] *= .79
    elif kind == "rest":
        s["calm"] += .22 * (1 - s["calm"])
        s["frustration"] *= .55
        s["curiosity"] += .02 * (1 - s["curiosity"])
    else:  # unsafe
        s["frustration"] += .20 * (1 - s["frustration"])
        s["calm"] *= .70
    s = {k: min(1., max(0., float(round(v, 8)))) for k, v in s.items()}
    if kind == "unsafe":
        decision = "stop_and_review"
    elif kind == "failed_attempt":
        decision = "simplify_next_trial"
    elif kind == "rest":
        decision = "repeat_known_safe_trial"
    elif s["curiosity"] >= .45 and s["confidence"] >= .38 and s["frustration"] <= .25:
        decision = "propose_one_tiny_novel_trial"
    else:
        decision = "repeat_known_safe_trial"
    return s, decision


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.db = sqlite3.connect(str(self.path), isolation_level=None, timeout=5)
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute("CREATE TABLE IF NOT EXISTS memory (name TEXT PRIMARY KEY, payload TEXT NOT NULL, sha256 TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, request_sha TEXT NOT NULL, report TEXT NOT NULL)")
        self.db.execute("INSERT OR IGNORE INTO memory VALUES(?,?,?)",
                        ("state", compact(asdict(State())), sha(asdict(State()))))
        self.read()  # Refuse malformed persisted state before any writes.

    def close(self):
        self.db.close()

    def read(self):
        row = self.db.execute("SELECT payload,sha256 FROM memory WHERE name='state'").fetchone()
        if row is None:
            raise ValueError("Missing affect ledger state")
        value = json.loads(row[0])
        if sha(value) != row[1]:
            raise ValueError("Corrupt affect state checksum")
        check_state(value)
        return value

    def apply(self, event):
        checked_event(event)
        request_sha = sha(event)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            old = self.db.execute("SELECT request_sha,report FROM events WHERE id=?", (event["id"],)).fetchone()
            if old:
                if old[0] != request_sha:
                    raise ValueError("Conflicting replay id")
                report = json.loads(old[1])
                self.db.execute("COMMIT")
                return {**report, "replayed": True}
            count = self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            if count >= MAX_EVENTS:
                raise ValueError("Affect ledger event budget exhausted")
            before = self.read()
            after, decision = change(before, event)
            report = {"schema": SCHEMA, "event_id": event["id"],
                      "origin": event["origin"], "kind": event["kind"],
                      "state_before": before, "state_after": after,
                      "advisory_next_action": decision, "native_cycles_caused": 0,
                      "sexual_response_proxy_touched": False,
                      "claim": "synthetic_affect_state_not_lived_feeling",
                      "replayed": False}
            self.db.execute("UPDATE memory SET payload=?,sha256=? WHERE name='state'",
                            (compact(after), sha(after)))
            self.db.execute("INSERT INTO events VALUES(?,?,?)",
                            (event["id"], request_sha, compact(report)))
            self.db.execute("COMMIT")
            return report
        except BaseException:
            self.db.execute("ROLLBACK")
            raise


def synth_event(identifier, kind):
    if kind not in ("failed_attempt", "rest", "unsafe"):
        raise ValueError("Synthetic demo only supports negative/rest/unsafe counterfactual")
    return {"id": identifier, "origin": "synthetic_fixture", "kind": kind,
            "novelty": 0., "evidence_digest": sha({"synthetic": kind, "id": identifier})}


def demo(audit_path, output_dir):
    """One real audited aggregate input plus synthetic events; no robot body execution."""
    source = verify_audit(audit_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=False)
    dbpath = out / "research_affect.sqlite"
    event = {"id": "audited-motor-progress", "origin": "verified_previous_motor_audit",
             "kind": "progress", "novelty": .8, "evidence_digest": source["audit_sha256"]}
    with_path = []
    ledger = Ledger(dbpath)
    try:
        a = ledger.apply(event)
        b = ledger.apply(synth_event("counterfactual-failure", "failed_attempt"))
        c = ledger.apply(synth_event("counterfactual-rest", "rest"))
        with_path.extend((a, b, c))
        final_state = ledger.read()
    finally:
        ledger.close()
    cold = Ledger(dbpath)
    try:
        recovered = cold.read()
        repeated = cold.apply(event)
        count = cold.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        cold.close()
    if recovered != final_state or count != 3 or not repeated["replayed"]:
        raise AssertionError("Cold recovery or event replay not durable")
    report = {"schema": SCHEMA, "audit_source": source, "events": with_path,
              "cold_state_matches": True, "cold_replay_idempotent": True,
              "event_count": count, "native_cycles_caused": 0,
              "sexual_proxy_untouched": True,
              "interpretation": "new nonsexual advisory affect variables and decisions, not lived feelings or motor learning"}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return {"status": "synthetic_developmental_affect_demo_passed",
            "advice": [x["advisory_next_action"] for x in with_path],
            "curiosity_after_audit": a["state_after"]["curiosity"],
            "events": count, "cold_recovered": True,
            "no_actuation_or_sexual_activation": True}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--motor-audit", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(demo(a.motor_audit, a.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
