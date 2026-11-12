"""Executable research composition with explicit boundaries, no service executor."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from . import body, cognitive, evidence, recovery, state_models


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def catalogue():
    """Build the existing atlas and describe connected and catalogued interfaces."""
    return {"schema": "dios.unified-catalogue.v1", "body": body.inventory(),
            "cognition": cognitive.describe_interfaces(),
            "workload": recovery.describe_interfaces(),
            "complete_model_parameter_access": False,
            "limits": ["No access to underlying language-model weights or hidden states.",
                       "This catalogue does not execute models; unified-demo separately runs fixed native-model fixtures.",
                       "Native physics constants and 78kg physiological calibration remain incomplete."]}


def workload_from_export(advisor, record, *, now_s, tick):
    """Project validated simulation indices into advisory workload only.

    This path has no CognitiveSession, goal planner, evidence or permission input.
    Sympathy-regulation index is used as an authored pressure proxy; it is not a
    measured stress level. Stale or absent values become null, never zero.
    """
    if type(advisor) is not recovery.RecoveryAdvisor:
        raise ValueError("exact RecoveryAdvisor required")
    normalized = body.normalize_native(record, now_s=now_s)
    fields = normalized["minimum_state"]
    values = {}
    for target, source in (("stress", "sympathetic"), ("fatigue", "fatigue"), ("energy", "energy")):
        field = fields[source]
        rounding = math.floor if target == "energy" else math.ceil
        values[target] = (rounding(field["value"] * 1000)
                          if field["status"] == "caller_supplied_simulation" else None)
    result = advisor.step(tick=tick, **values)
    return {"body": normalized, "advice": result,
            "mapping": "multiply indices by1000; ceil pressure/fatigue, floor energy",
            "mapping_is_authored_not_calibrated": True,
            "updates_cognitive_evidence": False, "updates_goal_commitment": False}


def summary(snapshot):
    """Compact summary of an internally generated snapshot for the CLI."""
    inventory = snapshot["body"]["inventory"]
    return {"schema": snapshot["schema"], "snapshot_sha256": snapshot["snapshot_sha256"],
            "evidence_kind": snapshot["evidence_kind"],
            "body_models": [{k: model[k] for k in ("id", "mass_kg", "status")}
                            for model in inventory["models"]],
            "catalogue_counts": snapshot["catalogue_counts"],
            "native_model_counts": {name: model["counts"] for name, model in snapshot["native_models"]["models"].items()},
            "current_advisory": snapshot["cognitive"]["current_advisory"],
            "workload_state": snapshot["workload"]["after_goal_stop"]["state"],
            "native_observation_status": snapshot["body"]["dynamic"]["status"],
            "capabilities": snapshot["capabilities"],
            "execution_permitted": False, "external_actions_taken": 0,
            "subjective_experience_demonstrated": False}


def run_demo(directory: Path, *, now_utc: str, native_export=None, now_s=None):
    """Execute an inspectable offline integration episode in a new directory.

    Actual existing cognitive routines and pinned atlas/parser code run. Public
    receipts are frozen GitHub observations, not a live server query. An optional
    bounded native export can feed workload advice; missing input stays unknown.
    The fixed cognitive episode ends with a stop, which also stops workload advice.
    """
    directory = Path(directory)
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("unified demonstration requires an empty directory")
    # Validate all external input and source files before stateful cognitive work.
    public = evidence.snapshot(now_utc=now_utc)
    body_state = body.default_snapshot()
    advisor = recovery.RecoveryAdvisor()
    if native_export is None:
        if now_s is not None:
            raise ValueError("simulated time requires an explicit native export")
        before_stop = advisor.read()
    else:
        mapped = workload_from_export(advisor, native_export, now_s=now_s, tick=0)
        body_state["dynamic"] = mapped["body"]
        before_stop = mapped["advice"]
    directory.mkdir(parents=True, exist_ok=True)
    models = state_models.run_models(directory / "native-models")
    episode = cognitive.run_episode(directory / "cognitive")
    # The actual demonstrated planner stop, not body pressure, causes this halt.
    if episode["goals"]["recovered_stopped"]["reason"] != "stopped":
        raise ValueError("demonstrated goal stop did not persist")
    stopped = advisor.request_stop()
    checkpoint = advisor.checkpoint()
    restored = recovery.RecoveryAdvisor.restore(json.loads(_json(checkpoint))).read()
    if restored != stopped:
        raise ValueError("workload checkpoint continuity failed")
    inventory = body_state["inventory"]
    snapshot = {
        "schema": "dios.unified-snapshot.v1",
        "evidence_kind": "executed_offline_research_composition",
        "evaluated_at_utc": now_utc,
        "cognitive": episode, "body": body_state, "public_evidence": public,
        "native_models": models,
        "workload": {"before_goal_stop": before_stop, "after_goal_stop": stopped,
                     "recovered": restored, "policy": recovery.describe_interfaces(),
                     "pressure_changes_truth_or_permission": False},
        "catalogue_counts": {
            "native_export_parameters": len(inventory["native_parameters"]),
            "phenotype_definition_leaves": len(inventory["phenotype"]["parameters"]),
            "genome_allele_definitions": len(inventory["genome"]["allele_parameters"]),
            "affect_somatic_goal_definitions": len(inventory["affect_parameters"]),
            "neural_field_definitions": len(inventory["neural_parameters"]),
            "regional_proxy_definitions": len(inventory["regional_proxy_parameters"]),
            "cognitive_interfaces": len(cognitive.describe_interfaces()["interfaces"])},
        "capabilities": {
            "cognition_goals_memory_dissent": "executed_synthetic_episode",
            "body_atlas": "executed_pinned_registry_builder",
            "native_body": body_state["dynamic"]["source_kind"],
            "genome_neural_affect": "executed_fixed_native_fixtures_not_applied_to_body_or_llm",
            "ritual": "imported_authored_progress_not_mastery",
            "visual_director": "plan_only_not_rendered_or_runtime_wired",
            "server": "imported_frozen_owner_reports_not_live_telemetry",
            "desktop": "reported_web_shortcuts_authenticated_use_untested",
            "workload": "executed_advisory_controller_no_measured_benefit"},
        "implementation_sha256": {module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                                   for module in (body, cognitive, evidence, recovery, state_models)},
        "execution_permitted": False, "external_actions_taken": 0,
        "model_api_calls": 0, "native_cycles_executed": 0,
        "subjective_experience_demonstrated": False,
        "complete_model_parameter_access": False,
        "limitations": [
            "A reproducible integration episode is not a continuously running agent.",
            "Native-model fixtures execute reduced code; they are not LLM internals or evidence of general learning.",
            "Frozen public reports and caller-supplied exports do not authenticate their issuers.",
            "No chat/image request is routed from the desktop web shortcuts through this code.",
            "No local model, physical sensor, executor or authorization verifier is attached.",
            "Checksums detect consistency errors, not coordinated data-and-checksum replacement."]}
    snapshot["implementation_sha256"][__name__] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    snapshot["snapshot_sha256"] = hashlib.sha256(_json(snapshot).encode("utf-8")).hexdigest()
    # Exclusive files, inspectable local state; no uploads or implicit deployment.
    for name, value in (("snapshot.json", snapshot), ("workload.checkpoint.json", checkpoint)):
        with (directory / name).open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(_json(value))
    return snapshot
