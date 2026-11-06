"""Persistent, opt-in forecast memory tied to an unchanged Tadash body checkpoint.

Only an advisory simulation. It does not advance native body time, run
motors, change instinct state, or claim biological/subjective recovery.
All updates require an explicit operator call on a locked BodyLoop session.
"""
from copy import deepcopy
import json
import re

from reflection_cycle import canonical, digest
from .autonomic_recovery_probe import FIELDS, forecast, _unit
from .host import BodyLoop
from .instinct import _snapshot

KEY = "nasuraya-recovery-memory/1"
SCOPE = "bounded_forecast_ledger_no_native_actuation"
MAX_EVENTS = 64


class RecoveryMemory:
    def __init__(self, loop):
        if not isinstance(loop, BodyLoop):
            raise ValueError("locked BodyLoop session required")
        self.loop = loop
        self._load()

    @staticmethod
    def _store(loop, saved):
        envelope = {"value": saved, "sha256": digest(saved)}
        loop.engine.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)",
                               (KEY, canonical(envelope)))

    @classmethod
    def enable(cls, loop):
        if not isinstance(loop, BodyLoop):
            raise ValueError("locked BodyLoop session required")
        row = loop.engine.db.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
        if row is None:
            native = _snapshot(loop)
            saved = {
                "schema": KEY, "scope": SCOPE, "enabled": True,
                "native_config_digest": digest(loop.config),
                "baseline_sha256": native["checkpoint_sha256"],
                "projection": deepcopy(native["values"]),
                "ticks": 0, "history": []
            }
            cls._store(loop, saved)
        else:
            controller = cls(loop)
            saved = controller._load()
            controller._require_same_checkpoint(saved)
            if not saved["enabled"]:
                saved["enabled"] = True
                cls._store(loop, saved)
        return cls(loop)

    def _load(self):
        row = self.loop.engine.db.execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
        if row is None:
            raise ValueError("recovery memory not enabled")
        envelope = json.loads(row[0])
        saved = envelope.get("value")
        if not isinstance(saved, dict) or envelope.get("sha256") != digest(saved):
            raise ValueError("recovery memory checksum mismatch")
        if (saved.get("schema") != KEY or saved.get("scope") != SCOPE or
                saved.get("native_config_digest") != digest(self.loop.config) or
                type(saved.get("enabled")) is not bool):
            raise ValueError("recovery memory identity mismatch")
        if not isinstance(saved.get("baseline_sha256"), str) or len(saved["baseline_sha256"]) != 64:
            raise ValueError("invalid baseline checkpoint")
        projection = saved.get("projection")
        if not isinstance(projection, dict) or set(projection) != set(FIELDS):
            raise ValueError("invalid recovery state")
        for value in projection.values():
            _unit(value)
        history = saved.get("history")
        if (type(saved.get("ticks")) is not int or saved["ticks"] < 0 or
                not isinstance(history, list) or
                len(history) != saved["ticks"] or len(history) > MAX_EVENTS):
            raise ValueError("invalid recovery event ledger")
        if any(not isinstance(row, dict) or
               not isinstance(row.get("id"), str) or
               not isinstance(row.get("steps"), int) or
               type(row.get("steps")) is bool or
               not 1 <= row["steps"] <= 20 or
               not isinstance(row.get("report"), dict) for row in history):
            raise ValueError("invalid recovery history event")
        if len(set(row["id"] for row in history)) != len(history):
            raise ValueError("duplicate recovery event")
        return saved

    def _require_same_checkpoint(self, saved):
        current = _snapshot(self.loop)
        if current["checkpoint_sha256"] != saved["baseline_sha256"]:
            raise ValueError("native checkpoint changed; forecast is stale")
        return current

    def status(self):
        saved = self._load()
        current = _snapshot(self.loop)
        return {
            "schema": KEY, "enabled": saved["enabled"],
            "events_recorded": saved["ticks"],
            "native_checkpoint_sha256": current["checkpoint_sha256"],
            "baseline_sha256": saved["baseline_sha256"],
            "native_checkpoint_unchanged": current["checkpoint_sha256"] == saved["baseline_sha256"],
            "projected_autonomic_state": deepcopy(saved["projection"]),
            "last_event_id": saved["history"][-1]["id"] if saved["history"] else None,
            "native_cycles_caused": 0,
            "scope": SCOPE
        }

    def disable(self):
        saved = self._load()
        saved["enabled"] = False
        self._store(self.loop, saved)
        return self.status()

    def step(self, event_id, *, steps=1):
        if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", event_id):
            raise ValueError("safe recovery event id required")
        if type(steps) is not int or not 1 <= steps <= 20:
            raise ValueError("recovery steps must be 1..20")
        saved = self._load()
        if not saved["enabled"]:
            raise ValueError("recovery memory disabled")
        self._require_same_checkpoint(saved)
        for record in saved["history"]:
            if record["id"] == event_id:
                if record["steps"] != steps:
                    raise ValueError("conflicting recovery event replay")
                report = deepcopy(record["report"])
                report["replayed"] = True
                return report
        if saved["ticks"] >= MAX_EVENTS:
            raise ValueError("recovery event budget exhausted")
        result = forecast(saved["projection"], steps=steps)
        projected = {key: result["steps"][-1][key] for key in FIELDS}
        self._require_same_checkpoint(saved)
        report = {
            "event_id": event_id, "forecast_steps": steps,
            "projected_autonomic_state": deepcopy(projected),
            "trajectory": result["steps"],
            "baseline_sha256": saved["baseline_sha256"],
            "replayed": False, "native_cycles_caused": 0,
            "actuation_authorized": False,
            "scope": SCOPE
        }
        saved["projection"] = projected
        saved["ticks"] += 1
        saved["history"].append({
            "id": event_id, "steps": steps, "report": deepcopy(report)
        })
        self._store(self.loop, saved)
        return report
