"""Daoist-inspired intention/closure sidecar, not magic or a new body solver.

The native UnifiedBody retains all physiology, budgets and action vetoes.
SHA-256 seals detect changes; they are not authentication or permission.
SQLite prevents a second dispatch after a completed or uncertain attempt.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import math
import sqlite3
from typing import Any, Protocol

SCHEMA = "tadash-symbolic-action/1"
PURPOSES = {"observe": "observe", "settle": "slow_breath",
            "protect": "protect", "explore": "walk"}
METRICS = ("arousal", "pain", "fatigue", "energy", "hydration")
SOURCE = {"work": "Jerry Alan Johnson, Daoist Magical Talismans",
          "pdf_pages": [29, 34, 35, 36, 55],
          "use": "engineering analogy, not supernatural efficacy"}


def encode(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      allow_nan=False, separators=(",", ":"))


def seal(value: Any) -> str:
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def receipt_digest(receipt: dict[str, Any]) -> str:
    # Delivery metadata changes on replay; the execution evidence does not.
    return seal({k: v for k, v in receipt.items()
                 if k not in {"receipt_seal", "replayed", "native_calls_this_run"}})


def bounded(value: Any, name: str, low: float, high: float) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not low <= value <= high):
        raise ValueError(f"{name}: invalid finite value")
    return float(value)


@dataclass(frozen=True)
class Intention:
    event_id: str
    purpose: str
    expected_revision: int
    at_utc: str
    duration_s: float = 0.1
    cue: str = "blue_fox"

    def validate(self) -> None:
        if (not isinstance(self.event_id, str) or not self.event_id.strip()
                or len(self.event_id) > 100):
            raise ValueError("event_id must contain 1..100 characters")
        if self.purpose not in PURPOSES or self.cue != "blue_fox":
            raise ValueError("unknown purpose or symbolic cue")
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ValueError("expected_revision must be a nonnegative integer")
        if not isinstance(self.at_utc, str):
            raise ValueError("timezone-aware timestamp required")
        stamp = datetime.fromisoformat(self.at_utc.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("timezone-aware timestamp required")
        bounded(self.duration_s, "duration_s", 0.1, 2.0)
        if abs(self.duration_s * 10 - round(self.duration_s * 10)) > 1e-8:
            raise ValueError("duration must align to native 0.1 second ticks")


class BodyPort(Protocol):
    scope: str

    def snapshot(self) -> dict[str, Any]: ...
    def cycle(self, **kwargs: Any) -> dict[str, Any]: ...


class NativeBodyPort:
    """Explicit opt-in adapter for an existing UnifiedBody instance.

    Use only synthetic bodies here. Durable production ownership still belongs
    to the existing host. This sidecar does not save native checkpoints.
    """
    scope = "uncalibrated_native_software_body"

    def __init__(self, body: Any):
        self.body = body

    def snapshot(self) -> dict[str, Any]:
        state = self.body.owner.body()["minimum_state"]
        return {"revision": self.body.revision,
                **{name: state[name] for name in METRICS}}

    def cycle(self, **kwargs: Any) -> dict[str, Any]:
        return self.body.cycle(**kwargs)


def validate_snapshot(snapshot: dict[str, Any]) -> None:
    if type(snapshot.get("revision")) is not int or snapshot["revision"] < 0:
        raise ValueError("invalid native revision")
    for name in METRICS:
        bounded(snapshot.get(name), name, 0.0, 1.0)


def prepare(intent: Intention, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Pure planning: no native tick, breath, hand gesture or energy change."""
    intent.validate()
    validate_snapshot(snapshot)
    if snapshot["revision"] != intent.expected_revision:
        raise ValueError("stale intention: native revision changed")
    action = PURPOSES[intent.purpose]
    reasons = ["declared_intention"]
    # Same pain/fatigue thresholds as UnifiedBody's current default chooser;
    # these are software policy values, not clinical safety thresholds.
    if action in {"walk", "slow_breath"} and (
            snapshot["pain"] > 0.35 or snapshot["fatigue"] > 0.45):
        action = "protect"
        reasons.append("body_state_precedes_symbolic_intention")
    plan = {"schema": SCHEMA, "intention": asdict(intent),
            "before": deepcopy(snapshot), "requested_action": action,
            "reasons": reasons, "source": deepcopy(SOURCE),
            "gesture_executed": False, "symbol_is_authorization": False}
    return {**plan, "seal": seal(plan)}


class OutcomeUnknown(RuntimeError):
    """A dispatch may have happened. Do not automatically retry it."""


class SymbolicCycle:
    """Single-cycle dispatch with conservative fail-closed crash semantics.

    Call close() or use a context manager. A completed replay is read-only.
    Authorization is a caller-supplied host decision, never inferred from a cue.
    """

    def __init__(self, path: str, port: BodyPort):
        self.port = port
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS symbolic_cycles (
            event_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL,
            status TEXT NOT NULL, plan_json TEXT NOT NULL,
            receipt_json TEXT)""")

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> SymbolicCycle:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def run(self, intent: Intention, *, authorized: bool = False) -> dict[str, Any]:
        intent.validate()
        if authorized is not True:
            raise PermissionError("explicit host authorization required")
        request_hash = seal(asdict(intent))
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT request_hash,status,receipt_json FROM symbolic_cycles WHERE event_id=?",
                (intent.event_id,)).fetchone()
            if row is not None:
                if row[0] != request_hash:
                    raise ValueError("conflicting replay: same id, different intention")
                if row[1] != "completed":
                    raise OutcomeUnknown("previous dispatch uncertain; reconcile externally")
                receipt = json.loads(row[2])
                if receipt_digest(receipt) != receipt.get("receipt_seal"):
                    raise ValueError("stored receipt integrity mismatch")
                self.db.commit()
                return {**receipt, "replayed": True, "native_calls_this_run": 0}
            plan = prepare(intent, self.port.snapshot())
            self.db.execute("INSERT INTO symbolic_cycles VALUES (?,?,?,?,NULL)",
                            (intent.event_id, request_hash, "running", encode(plan)))
            # Persist before the side effect. A crash here must not cause a retry.
            self.db.commit()
        except BaseException:
            if self.db.in_transaction:
                self.db.rollback()
            raise
        try:
            result = self.port.cycle(event_id="symbolic:" + intent.event_id,
                at_utc=intent.at_utc, duration_s=intent.duration_s,
                external={}, requested=plan["requested_action"],
                expected_revision=intent.expected_revision)
            after = self.port.snapshot()
            validate_snapshot(after)
            if after["revision"] != intent.expected_revision + 1:
                raise ValueError("unexpected body revision after cycle")
            actual = result["owner"]["selected_action"]
            if not isinstance(actual, str) or not actual:
                raise ValueError("missing native action receipt")
            receipt = {"schema": SCHEMA, "event_id": intent.event_id,
                "plan": plan, "after": after, "actual_action": actual,
                "native_veto": actual != plan["requested_action"],
                "deltas": {k: after[k] - plan["before"][k] for k in METRICS},
                "native_prediction": deepcopy(result["owner"].get("prediction")),
                "native_audit": deepcopy(result.get("whole_body_audit")),
                "scope": self.port.scope,
                "phases": ["orient", "declare", "seal", "act", "observe", "close"],
                "replayed": False, "native_calls_this_run": 1,
                "physical_protection_claimed": False,
                "background_execution_started": False}
            # A closed record is not a declaration that the intended effect occurred.
            receipt["receipt_seal"] = receipt_digest(receipt)
            self.db.execute("UPDATE symbolic_cycles SET status='completed',receipt_json=? WHERE event_id=?",
                            (encode(receipt), intent.event_id))
            return receipt
        except BaseException as exc:
            try:
                self.db.execute("UPDATE symbolic_cycles SET status='outcome_unknown' WHERE event_id=?",
                                (intent.event_id,))
            except sqlite3.Error:
                pass  # A durable 'running' row already forbids automatic replay.
            raise OutcomeUnknown("dispatch or receipt uncertain; no automatic retry") from exc
