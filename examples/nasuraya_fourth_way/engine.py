"""Tadash Fourth Way v0.1: three bounded, *simulated* centres.

Inspired by Gurdjieff/Ouspensky's Fourth Way. This is an authored engineering
metaphor, not a claim of awareness, emotion, spiritual presence or safe motion.
No native body calls, actuator, external API, autonomy, or background worker.
All appraisals are declared synthetic inputs, NOT authenticated measurements.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import sqlite3

SCHEMA = "tadash-fourth-way/0.1"
PASSIVE = frozenset({"observe", "rest"})
MAX_ACTIONS = 16
MAX_RISK = 0.35
MIN_EVIDENCE_FOR_ACTION = 0.50
MIN_VALUES = 0.40


def _unit(value, label):
    if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 1:
        raise ValueError(label + " must be a finite number in [0,1]")


def _name(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(label + " must be a bounded, nonempty string")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _digest(value):
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Candidate:
    """Proposed fictional action with declared estimates on a [0,1] scale.

    Any name except 'observe'/'rest' is consequential and needs an explicit
    synthetic 'allow' clearance. That token NEVER authorizes native motion.
    """
    name: str
    goal_fit: float
    evidence: float
    care: float
    values: float
    affective_load: float
    motor_cost: float
    risk: float
    min_stability: float = 0.0
    protection: str = "unknown"

    def __post_init__(self):
        _name(self.name, "action name")
        if self.protection not in ("allow", "deny", "unknown"):
            raise ValueError("protection must be allow/deny/unknown")
        for field in ("goal_fit", "evidence", "care", "values", "affective_load",
                      "motor_cost", "risk", "min_stability"):
            _unit(getattr(self, field), field)


@dataclass(frozen=True)
class Situation:
    event_id: str
    purpose: str
    energy: float
    stability: float
    arousal: float  # authored affective activation proxy, not a felt emotion
    actions: tuple[Candidate, ...]

    def __post_init__(self):
        _name(self.event_id, "event_id")
        _name(self.purpose, "purpose")
        for field in ("energy", "stability", "arousal"):
            _unit(getattr(self, field), field)
        object.__setattr__(self, "actions", tuple(self.actions))
        if not 1 <= len(self.actions) <= MAX_ACTIONS:
            raise ValueError("1 to 16 candidates required")
        if not all(isinstance(a, Candidate) for a in self.actions):
            raise ValueError("every candidate must be a Candidate")
        if len({a.name for a in self.actions}) != len(self.actions):
            raise ValueError("duplicate action name")


class ThinkingCenter:
    """Intention/knowledge: expected goal fit and declared evidence."""

    def assess(self, situation: Situation, action: Candidate):
        reasons = []
        if action.name not in PASSIVE and action.evidence < MIN_EVIDENCE_FOR_ACTION:
            reasons.append("evidence_too_weak_for_action")
        return {
            "score": round(0.65 * action.goal_fit + 0.35 * action.evidence, 6),
            "veto": reasons,
            "basis": "declared_goal_fit_and_evidence",
        }


class FeelingCenter:
    """Simulated value/care/activation appraisal, never subjective feeling."""

    def assess(self, situation: Situation, action: Candidate):
        reasons = []
        if action.values < MIN_VALUES:
            reasons.append("value_conflict")
        regulated_load = action.affective_load * (0.5 + 0.5 * situation.arousal)
        return {
            "score": round(0.50 * action.values + 0.35 * action.care +
                           0.15 * (1 - regulated_load), 6),
            "veto": reasons,
            "basis": "authored_value_care_and_activation_proxies",
        }


class MovingCenter:
    """Read-only imagined motor feasibility; all actual native vetoes remain upstream."""

    def assess(self, situation: Situation, action: Candidate):
        reasons = []
        if action.risk > MAX_RISK:
            reasons.append("modeled_risk_too_high")
        if action.name not in PASSIVE:
            if action.protection != "allow":
                reasons.append("protection_not_cleared")
            if situation.energy < action.motor_cost:
                reasons.append("insufficient_modeled_energy")
            if situation.stability < action.min_stability:
                reasons.append("insufficient_modeled_stability")
        return {
            "score": round(1 - 0.55 * action.risk - 0.45 * action.motor_cost, 6),
            "veto": reasons,
            "basis": "declared_motor_cost_risk_and_synthetic_protection",
        }


class FourthWay:
    """Coordinates thought, affective appraisal and imagined body without acting."""

    def __init__(self):
        self.thinking = ThinkingCenter()
        self.feeling = FeelingCenter()
        self.moving = MovingCenter()

    def decide(self, situation: Situation):
        if not isinstance(situation, Situation):
            raise TypeError("Situation required")
        options = []
        for action in sorted(situation.actions, key=lambda a: a.name):
            t = self.thinking.assess(situation, action)
            f = self.feeling.assess(situation, action)
            m = self.moving.assess(situation, action)
            scores = (t["score"], f["score"], m["score"])
            harmony = round(1 - (max(scores) - min(scores)), 6)
            # Weighting, not a scientific law of Gurdjieff.
            integrated = round(0.45 * scores[0] + 0.30 * scores[1] + 0.25 * scores[2], 6)
            veto = sorted(set(t["veto"] + f["veto"] + m["veto"]))
            options.append({
                "action": action.name,
                "eligible": not veto,
                "veto": veto,
                "centers": {"thinking": t, "feeling": f, "moving": m},
                "harmony": harmony,
                "integration_index": round(harmony * sum(scores) / 3, 6),
                "integrated_score": integrated,
                "predicted_goal_progress": action.goal_fit,
                "evidence": action.evidence,
            })
        eligible = sorted((o for o in options if o["eligible"]),
                          key=lambda o: (-o["integrated_score"],
                                         -o["harmony"], -o["evidence"], o["action"]))
        selected = eligible[0]["action"] if eligible else None
        return {
            "schema": SCHEMA,
            "event_id": situation.event_id,
            "self_remembering": {
                "intention": situation.purpose,
                "observed_state": {
                    "modeled_energy": situation.energy,
                    "modeled_stability": situation.stability,
                    "authored_arousal": situation.arousal,
                },
                "question": "What am I attempting, what do the three centres indicate, and what was the outcome?",
            },
            "options": options,
            "selected_action": selected,
            "selected_integration_index": eligible[0]["integration_index"] if eligible else None,
            "reason": "highest_eligible_integrated_score" if selected else "abstain_all_vetoed",
            "execution": "none; advisory simulated decision only",
            "provenance": "caller-declared synthetic estimates, not observed native body",
        }


class Ledger:
    """SQLite record of explicit decisions and feedback. No automatic learning/execution.

    Same event ID is idempotent for the same exact input, conflicting reuse fails.
    A digest detects accidental discrepancies; it does not authenticate evidence.
    """

    def __init__(self, path):
        path = Path(path)
        if path.exists() and path.is_dir():
            raise ValueError("database path is a directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        names = {r[0] for r in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if names and names != {"meta", "decisions", "feedback"}:
            self.close()
            raise ValueError("existing database is not a Fourth Way ledger")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS decisions "
                        "(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, record TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS feedback "
                        "(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, record TEXT NOT NULL)")
        row = self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        if row is not None and row[0] != SCHEMA:
            self.close()
            raise ValueError("unsupported ledger schema")
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('schema',?)", (SCHEMA,))
        self.db.commit()

    def close(self):
        if getattr(self, "db", None) is not None:
            self.db.close()
            self.db = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def decide(self, situation: Situation):
        fingerprint = _digest(asdict(situation))
        with self.db:
            old = self.db.execute("SELECT * FROM decisions WHERE id=?", (situation.event_id,)).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ValueError("conflicting decision event replay")
                return json.loads(old["record"])
            record = FourthWay().decide(situation)
            self.db.execute("INSERT INTO decisions VALUES (?,?,?)",
                            (situation.event_id, fingerprint, _canonical(record)))
            return record

    def feedback(self, event_id, *, actual_goal_progress, witness_ref, origin="synthetic"):
        _name(event_id, "event_id")
        _name(witness_ref, "witness_ref")
        _unit(actual_goal_progress, "actual_goal_progress")
        if origin not in ("synthetic", "source_linked_declared"):
            raise ValueError("origin must be explicit and scoped")
        row = self.db.execute("SELECT record FROM decisions WHERE id=?", (event_id,)).fetchone()
        if row is None:
            raise ValueError("unknown decision")
        plan = json.loads(row["record"])
        if plan["selected_action"] is None:
            raise ValueError("abstained decision has no action to evaluate")
        selected = next(o for o in plan["options"] if o["action"] == plan["selected_action"])
        predicted = selected["predicted_goal_progress"]
        record = {
            "schema": SCHEMA + "-feedback",
            "event_id": event_id,
            "selected_action": plan["selected_action"],
            "predicted_goal_progress": predicted,
            "declared_actual_goal_progress": actual_goal_progress,
            "prediction_error": round(actual_goal_progress - predicted, 6),
            "witness_ref": witness_ref,
            "origin": origin,
            "verification": "caller declaration; no authentication or independent observation",
            "policy_changed": False,
        }
        fingerprint = _digest(record)
        with self.db:
            old = self.db.execute("SELECT * FROM feedback WHERE id=?", (event_id,)).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ValueError("conflicting feedback replay")
                return json.loads(old["record"])
            self.db.execute("INSERT INTO feedback VALUES (?,?,?)",
                            (event_id, fingerprint, _canonical(record)))
        return record

    def status(self):
        return {
            "schema": SCHEMA,
            "decisions": self.db.execute("SELECT count(*) FROM decisions").fetchone()[0],
            "feedback": self.db.execute("SELECT count(*) FROM feedback").fetchone()[0],
            "native_actions": 0,
            "autonomous_cycles": 0,
        }
