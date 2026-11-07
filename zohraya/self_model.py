"""Read-only interoceptive projection of the existing Tadash body audit.

This module does not create a second energy reservoir, durable memory, sensor,
or decision actuator. The UnifiedBody checkpoint remains the sole owner of
simulated state, and audit_self_model.assess remains the input authority.
All output indices are uncalibrated engineering heuristics, not experiences.
"""

import math
from typing import Any, Dict, Mapping

AUDIT_SCHEMA = "nasuraya-audited-self-model/1.0"
SCHEMA = "zohraya-interoceptive-projection/1.0"


def _unit(value: Any, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be within [0, 1]")
    return float(value)


def _error(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("prediction error must be finite and nonnegative")
    return float(value)


class SelfModel:
    """A stateless identity-scoped view of an already-audited simulated body.

    Use ``SelfModel(agent_id).get_telemetry(audit_self_model.assess(body))``.
    The audit is an immutable input; no state or memory is ever mutated here.
    """

    def __init__(self, agent_id: str = "ZOHRAYA-CORE-01") -> None:
        if not isinstance(agent_id, str) or not agent_id.strip() or len(agent_id) > 128:
            raise ValueError("nonempty agent_id (max 128 characters) required")
        self.agent_id = agent_id

    def get_telemetry(self, audit: Mapping[str, Any]) -> Dict[str, Any]:
        if not isinstance(audit, Mapping) or audit.get("schema") != AUDIT_SCHEMA:
            raise ValueError("expected a Tadash audited self-model packet")
        revision = audit.get("body_revision")
        if type(revision) is not int or revision < 0:
            raise ValueError("body_revision must be a nonnegative integer")
        fresh = audit.get("body_state_fresh")
        guard = audit.get("upper_controller_walk_guard_allows")
        if type(fresh) is not bool or type(guard) is not bool:
            raise ValueError("audit freshness and guard flags must be boolean")
        state = audit.get("saved_minimum_state")
        if not isinstance(state, Mapping):
            raise ValueError("saved_minimum_state must be a mapping")
        energy = _unit(state.get("energy"), "energy")
        fatigue = _unit(state.get("fatigue"), "fatigue")
        pain = _unit(state.get("pain"), "pain")
        sleep_pressure = _unit(state.get("sleep_pressure"), "sleep_pressure")
        errors = audit.get("recent_prediction_errors")
        if not isinstance(errors, list) or len(errors) > 16:
            raise ValueError("recent_prediction_errors must be a list of <=16 values")
        ema = 0.0
        for value in errors:
            ema = 0.8 * ema + 0.2 * _error(value)
        ema = round(ema, 6)
        pressure = min(1.0, ema / 10.0)
        drive = round(min(1.0, max(0.0,
            0.45 * (1.0 - energy) + 0.20 * fatigue + 0.15 * pain
            + 0.15 * sleep_pressure + 0.05 * pressure)), 6)
        unknown = audit.get("unknown")
        if not isinstance(unknown, list) or not all(isinstance(x, str) for x in unknown):
            raise ValueError("unknown must be a list of strings")
        if not fresh:
            status = "STALE_EVIDENCE"
        elif energy <= 0.20:
            status = "CRITICAL_SIMULATED_ENERGY"
        elif not guard:
            status = "PROTECTIVE_GUARD"
        elif drive >= 0.40:
            status = "COMPENSATORY"
        else:
            status = "OPTIMAL"
        return {
            "schema": SCHEMA,
            "agent_id": self.agent_id,
            "cycle_count": revision,
            "source_audit_schema": AUDIT_SCHEMA,
            "source_kind": "saved_simulation_readout",
            "body_state_fresh": fresh,
            "energy": round(energy * 100, 6),
            "integrity": None,  # Not measured by this upstream audit.
            "fatigue": fatigue,
            "pain": pain,
            "sleep_pressure": sleep_pressure,
            "prediction_error_ema": ema,
            "prediction_error_ema_scope": "last_up_to_16_saved_errors_reset_per_readout",
            "homeostatic_drive": drive,
            "homeostatic_drive_is": "uncalibrated_engineering_index",
            "operational_status": status,
            "optional_motion_permitted": fresh and guard,
            "unknown": sorted(set(unknown + ["physical_integrity_not_measured"])),
            "simulated_state_mutated": False,
        }
