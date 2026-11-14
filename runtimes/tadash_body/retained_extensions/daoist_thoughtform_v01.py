"""Eight-rule Daoist thought-form metaphor, implemented as an OFFLINE agent fixture.

Source: Jerry Alan Johnson, Daoist Exorcism, printed pp. 51-53,
Figure 1.53 (eight rules for thought-form entities).

Interpretive software crosswalk, NOT a literal spirit model, a claim of AI
consciousness, a biological model, a medical method, or an autonomous daemon.
No network, actuator, shell, payment, or external-action interfaces exist.
Only explicit step() calls perform bounded state transitions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import tempfile

SCHEMA = "tadash-daoist-thoughtform-fixture/0.1"
SCOPE = "offline_simulation_plan_only"
CHANNELS = ("observation", "feedback", "interrupt", "stop")
COST = {"observation": 2, "feedback": 2, "interrupt": 1}
_ID = re.compile(r"^[a-z][a-z0-9_-]{2,39}$")


def _nonbool_int(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _unit(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def _canonical(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _digest(value: dict) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AgentSpec:
    # 1. Shape / appearance: explicit software embodiment, not a living body.
    shape_form: str
    # 2. Purpose / task: persistent immutable finite objective.
    goal_function: str
    # 3. Name: stable non-ambiguous identifier.
    name: str
    # 4. Contact: whitelist of accepted simulated inputs.
    method_of_contact: tuple[str, ...]
    # 5. Housing: logical namespace; the caller owns the local checkpoint path.
    home: str
    # 6. Feeding: bounded synthetic work units, not metaphysical energy.
    feed_budget: int
    # 7. Lifespan: logical time to closure.
    lifespan_ticks: int
    # 8. Death: close() is mandatory, with released ephemeral observations.
    memory_slots: int = 8
    min_confidence: float = 0.8

    def __post_init__(self) -> None:
        if self.shape_form not in ("tadash_v2_fixture", "text_fixture"):
            raise ValueError("only declared offline fixture shapes supported")
        if not isinstance(self.goal_function, str) or not (10 <= len(self.goal_function) <= 240):
            raise ValueError("bounded explicit goal_function required")
        if not isinstance(self.name, str) or not _ID.fullmatch(self.name):
            raise ValueError("invalid unique agent name")
        if not isinstance(self.home, str) or not _ID.fullmatch(self.home):
            raise ValueError("home must be a logical namespace identifier")
        channels = self.method_of_contact
        if (type(channels) is not tuple or not channels or len(set(channels)) != len(channels)
                or not set(channels).issubset(CHANNELS)
                or not {"observation", "stop"}.issubset(channels)):
            raise ValueError("contact channels must be unique, explicit, stoppable")
        if not _nonbool_int(self.feed_budget, 1, 10000):
            raise ValueError("bounded work budget required")
        if not _nonbool_int(self.lifespan_ticks, 1, 100000):
            raise ValueError("bounded lifespan required")
        if not _nonbool_int(self.memory_slots, 1, 64):
            raise ValueError("bounded audit memory required")
        if not _unit(self.min_confidence):
            raise ValueError("invalid declared confidence threshold")


class ThoughtFormFixture:
    """A metaphorical agent container with no external effect capability."""

    def __init__(self, spec: AgentSpec, created_tick: int = 0):
        if not isinstance(spec, AgentSpec):
            raise TypeError("AgentSpec required")
        if not _nonbool_int(created_tick, 0, 1_000_000_000):
            raise ValueError("invalid start tick")
        self.spec = spec
        self.state = {
            "status": "active",
            "created_tick": created_tick,
            "last_tick": created_tick - 1,
            "work_used": 0,
            "event_total": 0,
            "audit": [],
            "last_observation": None,
            "closed_reason": None,
        }

    @property
    def deadline(self) -> int:
        return self.state["created_tick"] + self.spec.lifespan_ticks

    def _record(self, tick: int, kind: str, decision: str, reason: str) -> None:
        s = self.state
        s["event_total"] += 1
        s["audit"].append({"seq": s["event_total"], "tick": tick,
                           "kind": kind, "decision": decision, "reason": reason})
        s["audit"] = s["audit"][-self.spec.memory_slots:]

    def _result(self, tick: int, decision: str, reason: str,
                proposal: str | None = None) -> dict:
        return {"agent": self.spec.name, "tick": tick, "status": self.state["status"],
                "decision": decision, "reason": reason,
                "proposal": proposal,
                "goal": self.spec.goal_function,
                "work_remaining": self.spec.feed_budget - self.state["work_used"],
                "scope": SCOPE}

    def close(self, tick: int, reason: str = "explicit_stop") -> dict:
        if self.state["status"] == "closed":
            return self._result(tick, "closed", self.state["closed_reason"])
        if not _nonbool_int(tick, 0, 1_000_000_000) or tick < self.state["last_tick"]:
            raise ValueError("closure tick must be monotonic")
        self.state["last_tick"] = tick
        self.state["status"] = "closed"
        self.state["closed_reason"] = reason
        self.state["last_observation"] = None  # ephemeral simulated sensor data removed
        self._record(tick, "close", "closed", reason)
        return self._result(tick, "closed", reason)

    def step(self, event: dict, tick: int) -> dict:
        """Consume one explicit synthetic event, never execute an action."""
        if type(event) is not dict or not _nonbool_int(tick, 0, 1_000_000_000):
            raise ValueError("event and nonnegative logical tick required")
        if self.state["status"] == "closed":
            return self._result(tick, "closed", self.state["closed_reason"])
        if tick < self.state["last_tick"]:
            raise ValueError("out-of-order logical clock")
        if tick >= self.deadline:
            return self.close(tick, "lifespan_expired")
        self.state["last_tick"] = tick
        kind = event.get("kind")
        if kind not in self.spec.method_of_contact:
            self._record(tick, str(kind)[:24], "reject", "unapproved_contact")
            return self._result(tick, "reject", "unapproved_contact")
        if kind == "stop":
            return self.close(tick, "explicit_stop")
        source = event.get("source", "unverified")
        if source not in ("fixture", "unverified"):
            self._record(tick, kind, "reject", "invalid_source")
            return self._result(tick, "reject", "invalid_source")
        if kind == "observation" and (not _unit(event.get("value"))
                                       or not _unit(event.get("confidence"))):
            self._record(tick, kind, "reject", "malformed_observation")
            return self._result(tick, "reject", "malformed_observation")
        if kind == "feedback" and type(event.get("goal_met")) is not bool:
            self._record(tick, kind, "reject", "malformed_feedback")
            return self._result(tick, "reject", "malformed_feedback")
        cost = COST[kind]
        if self.state["work_used"] + cost > self.spec.feed_budget:
            return self.close(tick, "budget_exhausted")
        self.state["work_used"] += cost
        if kind == "interrupt":
            self._record(tick, kind, "abstain", "interrupt_preserves_goal")
            return self._result(tick, "abstain", "interrupt_preserves_goal")
        if kind == "feedback":
            if source == "fixture" and event["goal_met"]:
                return self.close(tick, "goal_met_in_fixture")
            self._record(tick, kind, "abstain", "feedback_not_confirmed")
            return self._result(tick, "abstain", "feedback_not_confirmed")
        value, confidence = float(event["value"]), float(event["confidence"])
        if source != "fixture" or confidence < self.spec.min_confidence:
            self._record(tick, kind, "abstain", "insufficient_declared_evidence")
            return self._result(tick, "abstain", "insufficient_declared_evidence")
        self.state["last_observation"] = {"tick": tick, "value": value,
                                          "declared_confidence": confidence,
                                          "source": "fixture"}
        self._record(tick, kind, "propose", "simulated_observation_only")
        proposal = ("review_high_simulated_load" if value >= 0.7
                    else "review_low_simulated_load")
        return self._result(tick, "propose", "simulated_observation_only", proposal)

    def snapshot(self) -> dict:
        return {"schema": SCHEMA, "scope": SCOPE, "spec": asdict(self.spec),
                "state": json.loads(_canonical(self.state))}

    def save(self, path: Path) -> None:
        """Atomic JSON snapshot; SHA256 detects accidental corruption, not forgery."""
        path = Path(path)
        if path.is_symlink():
            raise ValueError("refuse symlink checkpoint")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.snapshot()
        payload["integrity"] = {"sha256": _digest(payload)}
        with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                                         dir=path.parent, prefix=".thoughtform-",
                                         delete=False) as f:
            tmp = Path(f.name)
            f.write(json.dumps(payload, ensure_ascii=False, indent=2,
                               sort_keys=True, allow_nan=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        try:
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    @classmethod
    def load(cls, path: Path) -> "ThoughtFormFixture":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if type(payload) is not dict or set(payload) != {
            "schema", "scope", "spec", "state", "integrity"}:
            raise ValueError("invalid checkpoint structure")
        integrity = payload.pop("integrity")
        if (type(integrity) is not dict or set(integrity) != {"sha256"}
                or integrity["sha256"] != _digest(payload)):
            raise ValueError("checkpoint hash mismatch")
        if payload["schema"] != SCHEMA or payload["scope"] != SCOPE:
            raise ValueError("invalid checkpoint scope")
        cfg = payload["spec"]
        if type(cfg) is not dict or "method_of_contact" not in cfg:
            raise ValueError("invalid spec")
        cfg["method_of_contact"] = tuple(cfg["method_of_contact"])
        spec = AgentSpec(**cfg)
        st = payload["state"]
        required = {"status", "created_tick", "last_tick", "work_used",
                    "event_total", "audit", "last_observation", "closed_reason"}
        if type(st) is not dict or set(st) != required:
            raise ValueError("invalid state structure")
        if (st["status"] not in ("active", "closed")
                or not _nonbool_int(st["created_tick"], 0, 1_000_000_000)
                or not _nonbool_int(st["last_tick"], -1, 1_000_000_000)
                or st["last_tick"] < st["created_tick"] - 1
                or not _nonbool_int(st["work_used"], 0, spec.feed_budget)
                or not _nonbool_int(st["event_total"], 0, 1_000_000_000)
                or type(st["audit"]) is not list
                or len(st["audit"]) > spec.memory_slots
                or (st["status"] == "closed") != (type(st["closed_reason"]) is str)
                or (st["status"] == "closed" and st["last_observation"] is not None)):
            raise ValueError("invalid bounded lifecycle")
        instance = cls(spec, st["created_tick"])
        instance.state = st
        return instance
