"""Explicit, reversible synthetic instinct channel attached to an existing BodyLoop.

This DOES NOT control limbs or invent physiology. It reads a source-pinned
native body checkpoint, keeps a separate motivation state in the same locked
SQLite session, and returns advisory-only plans. Nothing advances between
explicit invocations; no cloud model, actuator, or background schedule.
"""
from copy import deepcopy
from dataclasses import asdict
import json
import math
import re

from reflection_cycle import canonical, digest
from examples.nasuraya_research.tadash_motivation_probe_v01 import Event, State, transition
from .host import BodyLoop

KEY = "nasuraya-instinct/1"
SCOPE = "bounded_synthetic_motivation_advisory_only"
EVENT_FIELDS = set(Event.__dataclass_fields__) - {"name"}
EVENT_FIELDS.update({"id", "source"})
SOURCES = {"synthetic_fixture", "operator_report", "explicit_user_message"}
MAX_EVENTS = 128


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("finite normalized " + label + " required")
    return float(value)


def _snapshot(loop):
    # Reading the native checkpoint does not execute, simulate or alter body time.
    body = loop.body()
    native = body.owner.body()["minimum_state"]
    selected = {key: _number(native[key], key) for key in
                ("sympathetic", "parasympathetic", "arousal", "pain", "fatigue")}
    return {"checkpoint_sha256": body.checkpoint()["sha256"], "revision": body.revision,
            "values": selected, "source": "native_software_checkpoint_only"}


def _check_event(event):
    if type(event) is not dict or set(event) - EVENT_FIELDS:
        raise ValueError("unsupported instinct event field")
    if (type(event.get("id")) is not str or
            not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", event["id"])):
        raise ValueError("event id must be 1..64 safe characters")
    if event.get("source") not in SOURCES:
        raise ValueError("explicit event provenance required")
    if event.get("relationship") == "romantic" and event.get("adult_context") is not True:
        # Fail closed rather than converting a missing adult flag into a cue.
        raise ValueError("explicit adult_context=true required for romantic stimulus")
    params = {key: value for key, value in event.items() if key in EVENT_FIELDS - {"id", "source"}}
    proposed = Event(name=event["id"], **params)
    proposed.validate()
    return proposed


class InstinctController:
    """A user-enabled, recoverable fixture state on a locked native BodyLoop."""

    def __init__(self, loop):
        if not isinstance(loop, BodyLoop):
            raise ValueError("existing locked BodyLoop session required")
        self.loop = loop
        self._load()

    @classmethod
    def enable(cls, loop):
        if not isinstance(loop, BodyLoop):
            raise ValueError("existing locked BodyLoop session required")
        row = loop.engine.db.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
        if row is None:
            initial = {"schema": KEY, "scope": SCOPE, "enabled": True,
                       "native_config_digest": digest(loop.config),
                       "state": asdict(State()), "ticks": 0, "history": []}
            cls._store(loop, initial)
        else:
            controller = cls(loop)
            saved = controller._load()
            if not saved["enabled"]:
                saved["enabled"] = True
                controller._save(saved)
        return cls(loop)

    @staticmethod
    def _store(loop, data):
        env = {"value": data, "sha256": digest(data)}
        loop.engine.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)",
                               (KEY, canonical(env)))

    def _load(self):
        row = self.loop.engine.db.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
        if row is None:
            raise ValueError("instinct channel not enabled; use instinct-enable")
        envelope = json.loads(row[0])
        state = envelope["value"]
        if envelope.get("sha256") != digest(state):
            raise ValueError("instinct state checksum mismatch")
        if (state.get("schema") != KEY or state.get("scope") != SCOPE or
                state.get("native_config_digest") != digest(self.loop.config) or
                type(state.get("enabled")) is not bool):
            raise ValueError("instinct session identity mismatch")
        if type(state.get("ticks")) is not int or state["ticks"] < 0:
            raise ValueError("invalid instinct tick counter")
        values = state.get("state", {})
        if type(values) is not dict or set(values) != set(State.__dataclass_fields__):
            raise ValueError("invalid instinct state keys")
        for k, v in values.items():
            _number(v, k)
        history = state.get("history")
        if type(history) is not list or len(history) > MAX_EVENTS or len(history) != state["ticks"]:
            raise ValueError("invalid instinct history ledger")
        if len({x["id"] for x in history}) != len(history):
            raise ValueError("duplicate instinct event IDs in retained ledger")
        return state

    def _save(self, state):
        self._store(self.loop, state)

    def status(self):
        saved = self._load()
        return {"schema": KEY, "enabled": saved["enabled"],
                "events_recorded": saved["ticks"], "state": deepcopy(saved["state"]),
                "native_body": _snapshot(self.loop),
                "scope": SCOPE, "native_cycles_caused": 0}

    def disable(self):
        saved = self._load()
        saved["enabled"] = False
        self._save(saved)
        return self.status()

    def step(self, event):
        proposed = _check_event(event)
        saved = self._load()
        if not saved["enabled"]:
            raise ValueError("instinct channel disabled")
        eid = event["id"]
        request_digest = digest(event)
        for item in saved["history"]:
            if item["id"] == eid:
                if item["event_digest"] != request_digest:
                    raise ValueError("conflicting instinct event replay")
                prior = deepcopy(item["report"])
                prior["replayed"] = True
                return prior
        if saved["ticks"] >= MAX_EVENTS:
            raise ValueError("bounded instinct event budget exhausted")

        before = _snapshot(self.loop)
        body = before["values"]
        # The synthetic experiment conservatively reads pain and fatigue from
        # the verified body. Sympathetic elevation is a generic autonomic
        # load proxy; it is not equivalent to psychological stress.
        inferred_load = max(0.0, (body["sympathetic"] - .55) / .45)
        params = asdict(proposed)
        params["pain"] = max(params["pain"], body["pain"])
        params["fatigue"] = max(params["fatigue"], body["fatigue"])
        params["stress"] = max(params["stress"], inferred_load)
        params["adult_context"] = bool(params["adult_context"])
        state_before = State(**saved["state"])
        new_state, proposed_report = transition(state_before, Event(**params))

        after = _snapshot(self.loop)
        if after["checkpoint_sha256"] != before["checkpoint_sha256"]:
            raise ValueError("native checkpoint moved during instinct planning")
        report = {"event_id": eid, "source": event["source"],
                  "input_digest": request_digest,
                  "synthetic": proposed_report,
                  "native_observation": before,
                  "effective_inhibitors": {k: round(params[k], 6)
                      for k in ("pain", "fatigue", "stress")},
                  "decision_scope": "proposed_advisory_only",
                  "native_cycles_caused": 0, "replayed": False,
                  "claim_scope": "synthetic_engineering_fixture_only"}
        saved["state"] = asdict(new_state)
        saved["ticks"] += 1
        saved["history"].append({"id": eid, "event_digest": request_digest,
                                 "report": deepcopy(report)})
        self._save(saved)
        return report


def demo(output_dir):
    """Run an actual isolated, retained SQLite activation with no body motion."""
    from pathlib import Path
    from .host import BodyLoop
    output = Path(output_dir)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    with BodyLoop.start(output / "session.sqlite", mode="observe", max_actions=0) as loop:
        channel = InstinctController.enable(loop)
        events = [
            {"id": "family", "source": "synthetic_fixture", "relationship": "familial",
             "warmth": 0.9, "incentive": 0.9},
            {"id": "romantic", "source": "synthetic_fixture", "relationship": "romantic",
             "adult_context": True, "consent": "granted",
             "incentive": 0.85, "novelty": 0.3},
            {"id": "boundaries", "source": "synthetic_fixture", "relationship": "romantic",
             "adult_context": True, "consent": "refused", "incentive": 0.95},
            {"id": "recovery", "source": "synthetic_fixture",
             "confirmed_reward": 0.7},
        ]
        initial_hash = _snapshot(loop)["checkpoint_sha256"]
        reports = [channel.step(e) for e in events]
        result = channel.status()
        if _snapshot(loop)["checkpoint_sha256"] != initial_hash:
            raise AssertionError("isolated instinct must never advance the native body")
        if loop.status()["actions_reserved"] or loop.status()["completed_cycles"]:
            raise AssertionError("instinct demo executed a native action")
        if reports[0]["synthetic"]["sexual_response_proxy"] != 0:
            raise AssertionError("familial affection became sexual")
        if reports[2]["synthetic"]["action"] != "respect_boundary":
            raise AssertionError("explicit refusal was not respected")
        (output / "reports.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n")
        (output / "status.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    with BodyLoop(output / "session.sqlite") as loop:
        cold = InstinctController(loop).status()
    if cold["events_recorded"] != len(events):
        raise AssertionError("cold restart lost synthetic event history")
    return {"status": "activated_in_isolated_sqlite_session",
            "events": len(reports), "cold_recovery_passed": True,
            "native_cycles_caused": 0, "persisted": True,
            "session_path": str(output / "session.sqlite"),
            "scope": SCOPE}
