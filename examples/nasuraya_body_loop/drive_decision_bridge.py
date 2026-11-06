"""Read-only arbitration of a synthetic instinct report and Tadash body snapshot.

This is an advisory bridge, not a motor command, consent detector, or
biological interpretation. Hard behavioral constraints precede scoring.
"""
from math import isfinite


def _unit(value, name):
    if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 1:
        raise ValueError("invalid normalized " + name)
    return value


def advise(instinct_report):
    """Derive a bounded behavior proposal, fail closed on incomplete evidence."""
    if not isinstance(instinct_report, dict):
        raise ValueError("instinct report required")
    if (instinct_report.get("decision_scope") != "proposed_advisory_only" or
            instinct_report.get("native_cycles_caused") != 0 or
            instinct_report.get("claim_scope") != "synthetic_engineering_fixture_only"):
        raise ValueError("untrusted report scope")

    synthetic = instinct_report.get("synthetic")
    observation = instinct_report.get("native_observation")
    if not isinstance(synthetic, dict) or not isinstance(observation, dict):
        raise ValueError("missing evidence")
    if observation.get("source") != "native_software_checkpoint_only":
        raise ValueError("unsupported body source")
    values = observation.get("values")
    if not isinstance(values, dict):
        raise ValueError("missing native values")
    for key in ("pain", "fatigue", "sympathetic", "parasympathetic", "arousal"):
        _unit(values.get(key), key)
    for key in ("wanting", "sexual_response_proxy", "general_activation_proxy"):
        _unit(synthetic.get(key), key)
    action = synthetic.get("action")
    known = {"respect_boundary", "regulate_and_rest", "consider_mutual_closeness",
             "do_not_initiate_intimacy", "nonsexual_affiliation", "explore", "observe"}
    if action not in known:
        raise ValueError("unknown advice")
    pain = values["pain"]
    fatigue = values["fatigue"]
    autonomic_load = max(0., (values["sympathetic"] - .55) / .45)
    if action == "respect_boundary":
        decision = "respect_boundary"
        reason = "explicit_boundary_has_priority"
    elif pain >= .70 or fatigue >= .80 or autonomic_load >= .80:
        decision = "regulate_and_rest"
        reason = "native_body_protective_override"
    elif action == "regulate_and_rest":
        decision = "regulate_and_rest"
        reason = "instinct_protective_priority"
    else:
        decision = action
        reason = "synthetic_advisory_only"
    return {
        "proposal": decision,
        "reason": reason,
        "instinct_proposal": action,
        "native_checkpoint_sha256": observation.get("checkpoint_sha256"),
        "native_cycles_caused": 0,
        "actuation_authorized": False,
        "model": "tadash-readonly-arbiter/0.1",
    }
