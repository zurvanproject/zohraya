"""Opt-in Tadash sensory-to-action bridge derived from historical symbolic designs.

This is software state, not human anatomy, actual genitals, physiological
measurement, subjective experience, or a live actuator. The inherited native
BodyLoop is the sole authority for simulated body outcomes and protective veto.
No network calls or paid model access.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
import re

from reflection_cycle import InterruptedExecution, canonical, digest
from .host import BodyLoop, executed_body, validate_duration


KEY = "tadash-legacy-sensory-bridge/1"
SIGNALS = ("awakening", "safe_surrender", "warning", "invitation", "full_union")
REGIONS = ("none", "hand", "cheek", "shoulder", "pelvis", "perineum")

# Historical design concepts are translated into *labels* and abstract
# pathways. The descriptive map makes no claim that tissues are instantiated.
LEGACY_ATLAS = {
    "pudendal_aetheric_nexus": {
        "somatic_s2_s4": ("inferior_rectal", "perineal", "dorsal_clitoral"),
        "autonomic_s2_s4": "pelvic_splanchnic_reference_only",
        "sympathetic": "hypogastric_reference_only",
        "status": "synthetic_pathway_routing",
    },
    "pleasure_meaning_core": {
        "outputs": ("valence_proxy", "arousal_proxy", "chosen_signal"),
        "status": "computed_proxy_not_subjective_pleasure",
    },
    "tactile_memory": {"status": "receipt_linked_sqlite"},
    "communication": {"signals": SIGNALS, "status": "finite_state_selection"},
    "pelvis_perineum_anatomy": {
        "references": ("pelvic_floor", "bladder", "uterus", "rectum", "perineum"),
        "organ_meshes": False,
        "genital_mechanics": False,
        "status": "anatomical_reference_not_physical_model",
    },
    "autonomic_response": {
        "status": "normalized_heart_and_breath_proxies_not_vitals",
    },
}

_INPUT_KEYS = {"region", "presence", "contact", "consent", "distress"}


def normalized_input(stimulus):
    """Reject inferred consent, unknown zones, or non-finite sensory inputs."""
    if not isinstance(stimulus, dict) or set(stimulus) != _INPUT_KEYS:
        raise ValueError("explicit region/presence/contact/consent/distress required")
    if stimulus["region"] not in REGIONS:
        raise ValueError("unsupported anatomical region")
    if type(stimulus["consent"]) is not bool or type(stimulus["distress"]) is not bool:
        raise ValueError("consent and distress must be explicit booleans")
    for k in ("presence", "contact"):
        v = stimulus[k]
        if (type(v) not in (int, float) or not math.isfinite(v)
                or not 0 <= v <= 1):
            raise ValueError("finite, normalized input required: " + k)
    if stimulus["region"] == "none" and stimulus["contact"] > 0:
        raise ValueError("contact requires a region")
    return deepcopy(stimulus)


def transduce(state, snapshot, stimulus):
    """Pure synthetic afferent routing and preference; no action is executed."""
    s = normalized_input(stimulus)
    body = snapshot["minimum_state"]
    for k in ("fatigue", "sleep_pressure", "pain", "energy"):
        v = body[k]
        if type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1:
            raise ValueError("invalid native body observation: " + k)
    # Only S2-S4 perineal somatic inputs enter the pudendal abstract route.
    # Pelvic visceral reference is distinct; hand/face/shoulder are not pudendal.
    gated_contact = s["contact"] if s["consent"] and not s["distress"] else 0.
    paths = dict(pudendal_s2_s4=0., pelvic_visceral=0.,
                 trigeminal=0., cutaneous=0.)
    if s["region"] == "perineum":
        paths["pudendal_s2_s4"] = gated_contact
        paths["pelvic_visceral"] = .2 * gated_contact
    elif s["region"] == "pelvis":
        paths["pelvic_visceral"] = .7 * gated_contact
    elif s["region"] == "cheek":
        paths["trigeminal"] = gated_contact
    elif s["region"] in ("hand", "shoulder"):
        paths["cutaneous"] = gated_contact
    safe_memories = sum(bool(r["safe"]) for r in state["memory"])
    body_risk = body["pain"] > .4 or body["fatigue"] > .85 or body["energy"] < .1
    if not s["consent"] or s["distress"] or body_risk:
        signal = "warning"
    elif s["contact"] >= .35 and s["presence"] >= .5 and safe_memories >= 2:
        signal = "full_union"
    elif s["contact"] >= .25 and s["presence"] >= .4:
        signal = "invitation"
    elif s["presence"] >= .65:
        signal = "safe_surrender"
    else:
        signal = "awakening"
    gesture = {
        "awakening": "observe", "safe_surrender": "rest",
        "warning": "withdraw", "invitation": "approach",
        "full_union": "coordinate",
    }[signal]
    native_preference = "walk" if gesture in ("approach", "coordinate") else "observe"
    drive = min(1., .42 * s["presence"] + .38 * gated_contact
                + .2 * min(2, safe_memories) / 2)
    if signal == "warning":
        drive = 0.
    valence = max(0., min(1., .5 + .25 * s["presence"] + .1 * gated_contact
                             - (.5 if signal == "warning" else 0.)))
    return {
        "schema": KEY,
        "signal": signal,
        "symbolic_gesture": gesture,
        "native_preference": native_preference,
        "neural_pathways": paths,
        "body_source_sha256": snapshot["checkpoint_sha256"],
        "body_revision": snapshot["revision"],
        "meaning_core": {"valence_proxy": round(valence, 6),
                         "arousal_proxy": round(drive, 6),
                         "heart_rate_proxy_bpm": round(72 + 14 * drive, 3),
                         "breath_rate_proxy_per_min": round(13 + 4 * drive, 3)},
        "safe_memory_count": safe_memories,
        "consent_gate": "open" if s["consent"] and not s["distress"] else "closed",
        "scope": "synthetic neurological reference + finite state; no measured physiology",
    }


class TadashSensoryBridge:
    """Receipt-bound optional layer on a *real* native software body session."""

    def __init__(self, loop):
        if not isinstance(loop, BodyLoop):
            raise TypeError("a native BodyLoop instance is required")
        self.loop = loop
        self._load()

    @classmethod
    def enable(cls, loop):
        if not isinstance(loop, BodyLoop) or loop.config["mode"] != "bounded":
            raise ValueError("only an explicitly bounded native simulator can be enabled")
        state = {
            "schema": KEY, "enabled": True, "native_config": deepcopy(loop.config),
            "atlas": deepcopy(LEGACY_ATLAS), "memory": [], "intents": {},
            "last_signal": None, "scope": "synthetic_external_state_not_consciousness",
        }
        loop.engine.db.execute(
            "INSERT INTO meta VALUES(?,?)",
            (KEY, canonical({"value": state, "sha256": digest(state)})),
        )
        return cls(loop)

    def _load(self):
        row = self.loop.engine.db.execute(
            "SELECT value FROM meta WHERE key=?", (KEY,)
        ).fetchone()
        if row is None:
            raise ValueError("the sensory layer must be explicitly enabled")
        data = json.loads(row[0])
        state = data["value"]
        if (data["sha256"] != digest(state) or state["schema"] != KEY
                or state["native_config"] != self.loop.config
                or type(state["enabled"]) is not bool or not state["enabled"]
                or state["atlas"] != LEGACY_ATLAS):
            raise ValueError("sensory bridge integrity or native-session mismatch")
        return state

    def _save(self, state):
        self.loop.engine.db.execute(
            "UPDATE meta SET value=? WHERE key=?",
            (canonical({"value": state, "sha256": digest(state)}), KEY),
        )

    def status(self):
        state = self._load()
        return {
            "enabled": state["enabled"], "last_signal": state["last_signal"],
            "memory_count": len(state["memory"]), "atlas": deepcopy(state["atlas"]),
            "pending": [k for k, v in state["intents"].items() if v["result"] is None],
            "native_completed_cycles": self.loop.status()["completed_cycles"],
            "native_actions_remaining": self.loop.status()["actions_remaining"],
            "external_model_api_calls": 0, "physical_actuator_calls": 0,
            "subjective_experience_claim": False,
        }

    def _finish(self, state, event_id, record, *, replayed):
        intent = state["intents"][event_id]
        if intent["result"] is not None:
            result = deepcopy(intent["result"])
            result.update(replayed=True, this_call_native_cycles=0)
            return result
        evidence = record.get("request", {}).get("evidence", [])
        if (record["id"] != intent["native_id"] or
                not evidence or evidence[0].get("source_sha256") !=
                intent["before_checkpoint_sha256"]):
            raise ValueError("native receipt does not match the frozen sensory intent")
        receipt = self.loop.receipt(record, replayed=replayed)
        executed = executed_body(record)
        source = "native-decision://" + record["id"] + "/" + digest(record) if executed else None
        result = {
            "event_id": event_id, "status": receipt["status"],
            "plan": deepcopy(intent["plan"]), "native_receipt": receipt,
            "native_provenance": source, "replayed": replayed,
            "this_call_native_cycles": int(executed and not replayed),
            "scope": "finite sensory preference and observed native software result",
        }
        if executed:
            state["memory"].append({
                "event_id": event_id, "region": intent["stimulus"]["region"],
                "signal": intent["plan"]["signal"],
                "safe": intent["plan"]["consent_gate"] == "open"
                    and intent["plan"]["signal"] != "warning",
                "gesture": intent["plan"]["symbolic_gesture"],
                "actual_native_action": receipt["actual_action"],
                "before_checkpoint_sha256": intent["before_checkpoint_sha256"],
                "after_checkpoint_sha256": receipt["self_model_after"]["checkpoint_sha256"],
                "source": source, "kind": "observed_software_outcome",
            })
            state["last_signal"] = intent["plan"]["signal"]
        intent["result"] = deepcopy(result)
        self._save(state)
        return result

    def step(self, event_id, stimulus, *, duration_s=.1):
        validate_duration(duration_s)
        s = normalized_input(stimulus)
        if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,60}", event_id):
            raise ValueError("bounded event ID required")
        state = self._load()
        intent = state["intents"].get(event_id)
        if intent is not None:
            if intent["stimulus"] != s or intent["duration_s"] != duration_s:
                raise ValueError("conflicting sensory replay")
            if intent["result"] is not None:
                result = deepcopy(intent["result"])
                result.update(replayed=True, this_call_native_cycles=0)
                return result
            record = self.loop.engine.get(intent["native_id"])
            if record is not None:
                if record["status"] != "complete":
                    raise InterruptedExecution("native sensory action still running")
                return self._finish(state, event_id, record, replayed=True)
            if self.loop.body().checkpoint()["sha256"] != intent["before_checkpoint_sha256"]:
                raise InterruptedExecution("body changed since reserved sensory intent")
        else:
            if any(i["result"] is None for i in state["intents"].values()):
                raise InterruptedExecution("reconcile earlier sensory intent first")
            if (self.loop.status()["unresolved_running"] or
                    self.loop.status()["actions_remaining"] <= 0):
                raise InterruptedExecution("native body unavailable or budget exhausted")
            native_id = "sensory:" + event_id
            if self.loop.engine.get(native_id) is not None:
                raise ValueError("native action ID already occupied")
            before = self.loop.observe()
            proposal = transduce(state, before, s)
            intent = {
                "native_id": native_id, "stimulus": s, "plan": proposal,
                "duration_s": duration_s,
                "before_checkpoint_sha256": before["checkpoint_sha256"],
                "result": None,
            }
            state["intents"][event_id] = intent
            self._save(state)  # The intent and prediction exist before native action.
        # A native action may be replayed after a crash, never silently reexecuted.
        self.loop.observe()
        self.loop.step(decision_id=intent["native_id"], duration_s=duration_s,
                       preferred_action=intent["plan"]["native_preference"])
        record = self.loop.engine.get(intent["native_id"])
        if record is None or record["status"] != "complete":
            raise InterruptedExecution("native software result not committed")
        return self._finish(state, event_id, record, replayed=False)
