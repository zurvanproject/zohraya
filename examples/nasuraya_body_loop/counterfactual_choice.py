"""Tadash counterfactual body-feedback decision experiment v0.1.

It answers: can the *policy* revise an intention when a synthetic body report
changes? This is not felt experience, autonomous agency or actual motion.
All counterfactual inputs remain explicitly synthetic and source-labelled.
"""
from copy import deepcopy
import json
import re

from reflection_cycle import canonical, digest
from .host import BodyLoop
from .drive_decision_bridge import advise, _unit

KEY = "nasuraya-choice-revision/1"
MAX_CASES = 32
SIGNALS = ("sympathetic", "parasympathetic", "arousal", "pain", "fatigue")


def reconsider(instinct_report, counterfactual):
    """Compare a real *software checkpoint* proposal to hypothetical body input."""
    first = advise(instinct_report)
    if not isinstance(counterfactual, dict):
        raise ValueError("explicit counterfactual body object required")
    if (counterfactual.get("source") != "synthetic_counterfactual_fixture" or
            counterfactual.get("baseline_native_checkpoint_sha256") !=
            first["native_checkpoint_sha256"]):
        raise ValueError("counterfactual provenance or baseline mismatch")
    values = counterfactual.get("values")
    if not isinstance(values, dict) or set(values) != set(SIGNALS):
        raise ValueError("five counterfactual body signals required")
    for signal in SIGNALS:
        _unit(values[signal], signal)
    initial = first["proposal"]
    load = max(0.0, (values["sympathetic"] - .55) / .45)
    # The permission/boundary rule always wins, including over counterfactuals.
    if initial == "respect_boundary":
        revised, reason = initial, "boundary_cannot_be_overridden"
    elif initial == "regulate_and_rest":
        revised, reason = initial, "protective_choice_not_lifted_by_hypothesis"
    elif values["pain"] >= .70 or values["fatigue"] >= .80 or load >= .80:
        revised, reason = "regulate_and_rest", "synthetic_body_feedback_protective_revision"
    else:
        revised, reason = initial, "no_revision_needed"
    return {
        "initial_choice": initial, "revised_choice": revised,
        "changed": revised != initial, "reason": reason,
        "native_checkpoint_sha256": first["native_checkpoint_sha256"],
        "counterfactual_source": "synthetic_counterfactual_fixture",
        "actuation_authorized": False, "native_cycles_caused": 0,
        "scope": "counterfactual_policy_test_only",
    }


class ChoiceRevisionMemory:
    """Idempotent SQLite ledger; uses a locked, existing synthetic BodyLoop."""
    def __init__(self, loop):
        if not isinstance(loop, BodyLoop):
            raise ValueError("existing locked body session required")
        self.loop = loop
        self._load()

    def _load(self):
        row = self.loop.engine.db.execute(
            "SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
        if row is None:
            return {"schema": KEY, "records": []}
        env = json.loads(row[0])
        state = env.get("value")
        if not isinstance(state, dict) or env.get("sha256") != digest(state):
            raise ValueError("revision ledger checksum mismatch")
        records = state.get("records")
        if (state.get("schema") != KEY or not isinstance(records, list) or
                len(records) > MAX_CASES or
                any(not isinstance(r, dict) or
                    not isinstance(r.get("id"), str) or
                    not isinstance(r.get("digest"), str) or
                    not isinstance(r.get("result"), dict) for r in records) or
                len({r["id"] for r in records}) != len(records)):
            raise ValueError("invalid revision ledger")
        return state

    def status(self):
        state = self._load()
        return {"schema": KEY, "cases": len(state["records"]),
                "last": deepcopy(state["records"][-1]["result"])
                        if state["records"] else None,
                "native_cycles_caused": 0}

    def step(self, event_id, instinct_report, counterfactual):
        if not isinstance(event_id, str) or not re.fullmatch(
                r"[A-Za-z0-9_.-]{1,64}", event_id):
            raise ValueError("safe revision event ID required")
        checkpoint = self.loop.body().checkpoint()["sha256"]
        first = advise(instinct_report)
        if checkpoint != first["native_checkpoint_sha256"]:
            raise ValueError("stale native body observation")
        request_hash = digest({
            "instinct_report": {k: v for k, v in instinct_report.items()
                               if k != "replayed"},
            "counterfactual": counterfactual,
        })
        state = self._load()
        for item in state["records"]:
            if item["id"] == event_id:
                if item["digest"] != request_hash:
                    raise ValueError("conflicting choice revision replay")
                return {**deepcopy(item["result"]), "replayed": True}
        if len(state["records"]) >= MAX_CASES:
            raise ValueError("revision case budget exhausted")
        result = reconsider(instinct_report, counterfactual)
        if self.loop.body().checkpoint()["sha256"] != checkpoint:
            raise ValueError("native body changed during advisory")
        result["replayed"] = False
        state["records"].append({
            "id": event_id, "digest": request_hash, "result": deepcopy(result)})
        self.loop.engine.db.execute(
            "INSERT OR REPLACE INTO meta VALUES(?,?)",
            (KEY, canonical({"value": state, "sha256": digest(state)})))
        return result
