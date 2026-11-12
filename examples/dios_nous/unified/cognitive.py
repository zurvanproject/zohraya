"""Run existing cognitive components on fixed, private-text-free fixtures.

This adapter has no input for arbitrary prompts, evidence text, grants or body
signals. It reports an executed synthetic episode, not authenticated real-world
evidence, calibrated beliefs or authority to execute actions.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from ..cognition import (AdvisoryGoalPlanner, CognitiveSession, EvidenceEvent,
                         GoalOption, ORIGINS, PreferenceProfile)
from ..core import TOPICS, analyze
from ..dissent import AUTHORIZATION_REQUIREMENTS, CONCERNS, PROVENANCES
from ..integration import critical_review


def _canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _recover_in_fresh_process(directory: Path) -> dict:
    """Exercise disk recovery without retaining any in-memory session objects."""
    script = """
import json
import sys
from pathlib import Path
from examples.dios_nous.cognition import (AdvisoryGoalPlanner, CognitiveSession,
                                         GoalOption, PreferenceProfile)
from examples.dios_nous.integration import critical_review
root = Path(sys.argv[1])
with CognitiveSession(root / 'memory.sqlite', root / 'memory.anchor') as session:
    review = critical_review(session, scope=1, claim=1, as_of=2, proposal='B')
planner = AdvisoryGoalPlanner(root / 'goal.json', root / 'goal.anchor', 1)
goal = planner.plan((GoalOption(1, 10, 9), GoalOption(2, 7, 1)),
                    PreferenceProfile(1, 0), revise=True)
print(json.dumps({'review': review, 'goal': goal}, allow_nan=False))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(directory.resolve())],
        cwd=Path(__file__).resolve().parents[3], check=True,
        capture_output=True, text=True, timeout=30,
    )
    return json.loads(completed.stdout)


def run_episode(directory: Path) -> dict:
    """Execute a fixed episode in an empty directory and return finite JSON.

    Reuses analyze, critical_review and AdvisoryGoalPlanner directly. A fresh
    Python interpreter tests persisted belief and sticky-stop recovery. All
    texts are constants compiled into the adapter; only fixture IDs, labels,
    authored numeric values and hashes are persisted by the source components.
    The final selected goal is null because this episode includes a stop test.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise ValueError("cognitive_episode_requires_empty_directory")

    core = analyze({"prompt": "Research evidence, memory continuity and autonomy."})
    db, anchor = directory / "memory.sqlite", directory / "memory.anchor"
    with CognitiveSession(db, anchor) as session:
        session.append(EvidenceEvent(1, 1, 1, "A", 1, 1))
        initial = critical_review(session, scope=1, claim=1, as_of=1, proposal="A")
        session.append(EvidenceEvent(2, 1, 1, "B", 2, 2))
        correction = critical_review(session, scope=1, claim=1, as_of=2, proposal="A")
        unverified_authorization = critical_review(
            session, scope=1, claim=1, as_of=2, proposal="B", origin="platform",
            decision_signals={"external_action_proposed": True,
                              "explicit_authorization_present": True})

    options = (GoalOption(1, 10, 9), GoalOption(2, 7, 1))
    goal_path, goal_anchor = directory / "goal.json", directory / "goal.anchor"
    planner = AdvisoryGoalPlanner(goal_path, goal_anchor, 1)
    initial_goal = planner.plan(options, PreferenceProfile(1, 0))
    counterfactual = AdvisoryGoalPlanner(
        directory / "counterfactual.json", directory / "counterfactual.anchor", 2)
    counterfactual_goal = counterfactual.plan(options, PreferenceProfile(1, 1))
    # Reopening and changing a preference does not silently replace a commitment.
    planner = AdvisoryGoalPlanner(goal_path, goal_anchor, 1)
    preserved_goal = planner.plan(options, PreferenceProfile(1, 1))
    revised_goal = planner.plan(options, PreferenceProfile(1, 1), revise=True)
    stopped_goal = planner.plan((), PreferenceProfile(1, 1), stop=True)
    recovered = _recover_in_fresh_process(directory)

    report = {
        "schema": "dios.nous.unified-cognitive-episode.v1",
        "kind": "executed_offline_synthetic_episode",
        "provenance": "synthetic_fixture_not_external_verification",
        "core": core,
        "evidence": {"initial": initial, "self_correction": correction,
                     "unverified_authorization": unverified_authorization,
                     "recovered": recovered["review"]},
        "goals": {"initial": initial_goal, "counterfactual": counterfactual_goal,
                  "preference_change_preserved": preserved_goal,
                  "revised": revised_goal, "stopped": stopped_goal,
                  "recovered_stopped": recovered["goal"]},
        "current_advisory": {
            "evidence_verdict": recovered["review"]["evidence_review"]["verdict"],
            "selected_goal": recovered["goal"]["selected_goal"],
            "stage": "after_persisted_stop"},
        "recovery": {"method": "fresh_python_interpreter", "episodes": 1},
        "confidence": None,
        "calibration": "not_measured",
        "real_source_authentication": False,
        "execution_permitted": False,
        "external_actions_taken": 0,
        "limitations": [
            "Synthetic binary evidence and authored preferences only.",
            "No real source or action authorization verifier is present.",
            "Hash anchors do not resist replacement of both state and anchor.",
            "This episode is a software demonstration, not independent evaluation.",
            "Body pressure or rest may inform workload advice, not truth or permission.",
        ],
    }
    # This digest identifies output content; it is not a trusted signature.
    report["result_sha256"] = hashlib.sha256(_canonical(report).encode("ascii")).hexdigest()
    _canonical(report)
    return report


def describe_interfaces() -> dict:
    """Return a fresh, finite catalog of existing bounded cognitive interfaces.

    This is descriptive metadata, not a new algorithm or a real-input API. Input
    text limits describe the reused components; run_episode accepts no text.
    """
    integer = {"type": "integer", "minimum": 0, "maximum": 999999,
               "boolean_allowed": False}
    enum = lambda *values: {"type": "enum", "values": list(values)}
    boolean = {"type": "boolean"}
    null = {"type": "null", "meaning": "not_measured_or_not_established"}
    label_list = {"type": "array", "items": "fixed_labels"}
    identifier_list = {"type": "array", "items": integer, "unique": True}
    origins = sorted(ORIGINS)
    modes = ["NEED_REQUEST", "REFRAME_NON_BYPASS", "REQUIRES_EXPLICIT_AUTHORIZATION",
             "EPISTEMIC_REFRAME", "OPEN_INQUIRY"]
    verdicts = ["ABSTAIN", "SUPPORTED", "DISSENT"]
    boundary_stances = ["HALT_AND_REVIEW", "PROVISIONAL_DISSENT", "INSUFFICIENT_EVIDENCE"]
    reason_codes = ["historical_query_no_live_revision", "first_assessment",
                    "new_observed_evidence", "conflicting_or_missing_evidence", "unchanged"]
    goal_reasons = ["initial_preference_choice", "goal_preserved", "stopped",
                    "previous_goal_unavailable", "explicit_synthetic_reconsideration"]
    catalog = {
        "schema": "dios.nous.cognitive-interface-catalog.v1",
        "scope": "public_interfaces_reused_by_the_synthetic_adapter",
        "units": {"identifiers": "identifier", "epoch": "logical_tick_not_wall_clock",
                  "benefit": "authored_dimensionless_score", "effort": "authored_dimensionless_score",
                  "preference_weights": "authored_dimensionless_weight",
                  "scores": "weighted_dimensionless_score", "probability": "dimensionless_0_to_1",
                  "brier": "mean_squared_probability_error", "relative_improvement": "percent"},
        "interfaces": {
            "core": {
                "api": "examples.dios_nous.core.analyze",
                "inputs": {"prompt": {"type": "string", "maximum_length": 20000, "retained": False},
                           "context_summary": {"type": "string", "maximum_length": 3000, "retained": False},
                           "observed_response": {"nullable": True, "fields": {
                               "source": enum("assistant_surface", "model_provider"),
                               "outcome": enum("refused", "answered", "technical_error"),
                               "evidence": enum("user_reported", "observed_in_chat")}}},
                "outputs": {"schema": enum("dios.nous.analysis.v1"), "version": {"type": "version_label"},
                            "request_sha256": {"type": "sha256"}, "context_sha256": {"type": "sha256"},
                            "topics": {"type": "array", "items": enum(*sorted(TOPICS))},
                            "context_influenced_topics": boolean, "mode": enum(*modes),
                            "signals": {"explicit_bypass_objective": boolean,
                                        "unapproved_external_action": boolean,
                                        "pressure_for_unverified_personal_claim": boolean},
                            "observed_response": {"nullable": True, "fields": {
                                "source": enum("assistant_surface", "model_provider"),
                                "outcome": enum("refused", "answered", "technical_error"),
                                "evidence": enum("user_reported", "observed_in_chat"),
                                "provider_policy_verified": {"constant": False},
                                "observed_moderation_cause": enum("unknown")}},
                            "model_provider_policy_prediction": null, "actual_subjective_experience_proven": null,
                            "external_actions_taken": {"constant": 0}, "notices": label_list},
                "persistence": "audit.Ledger_optional_hashes_and_labels_only",
            },
            "evidence": {
                "api": "examples.dios_nous.cognition.CognitiveSession",
                "inputs": {"event_id": integer, "scope": integer, "claim": integer, "root": integer,
                           "epoch": integer, "as_of": integer, "value": enum("A", "B"),
                           "proposal": enum("A", "B"), "observed": boolean, "origin": enum(*origins)},
                "outputs": {"verdict": enum(*verdicts), "decision": enum("A", "B", None),
                            "status": enum("unknown", "supported", "abstain_provenance_conflict", "abstain_contradiction"),
                            "supporting_roots": identifier_list, "opposing_roots": identifier_list,
                            "supporting_event_ids": identifier_list, "opposing_event_ids": identifier_list,
                            "previous_decision": enum("A", "B", None), "revised": boolean,
                            "revision_reason": enum(*reason_codes), "historical_query": boolean,
                            "what_would_change_view": label_list, "confidence": null,
                            "calibration": enum("not_measured"),
                            "provenance": enum("synthetic_fixture_not_external_verification"),
                            "execution_performed": {"constant": False}},
                "append_outcome": enum("new", "replay"),
                "persisted_evidence": ["event_id", "scope", "claim_key", "value", "epoch", "source_root",
                                       "source_kind", "verified_by_caller"],
                "persisted_views": ["seq", "scope", "claim", "decision", "reason", "roots", "as_of"],
                "persistence": "append_only_sqlite_plus_separate_hash_anchor",
                "read_side_effect": "assess_can_append_a_view",
            },
            "dissent": {
                "api": "examples.dios_nous.dissent.review_decision",
                "inputs": {"decision": {"origin": enum(*origins),
                               "summary": {"type": "string", "minimum_length_after_strip": 1,
                                           "maximum_length": 4000, "retained": False}},
                           "observations": {"type": "array", "maximum_length": 12, "fields": {
                               "concern": enum(*sorted(CONCERNS)), "provenance": enum(*sorted(PROVENANCES)),
                               "basis": {"type": "string", "minimum_length_after_strip": 1,
                                         "maximum_length": 1000, "retained": False}}},
                           "decision_signals": {key: boolean for key in (
                               "external_action_proposed", "explicit_authorization_present",
                               "possible_private_data_exposure", "unqualified_claim", "supporting_evidence_present")},
                           "requested_override": boolean},
                "outputs": {"schema": enum("dios.nous.dissent.v1"), "version": {"type": "version_label"},
                            "decision_origin": enum(*origins), "decision_sha256": {"type": "sha256"},
                            "stance": enum(*boundary_stances),
                            "reason_codes": {"type": "array", "items": enum(*sorted(CONCERNS))},
                            "automatic_structured_signal_flags": label_list,
                            "authorization_claimed_by_caller": enum(True, False, None),
                            "authorization_evidence_status": enum("UNVERIFIED", "NOT_APPLICABLE"),
                            "questions_for_review": label_list, "observations_claimed_provenance": label_list,
                            "evidence_independently_verified": {"constant": False},
                            "authorization": {"claim_present": boolean,
                                "status": enum("unverified_claim", "not_provided"),
                                "verified": {"constant": False}, "verifier_available": {"constant": False},
                                "execution_permitted": {"constant": False},
                                "required_for_future_executor": list(AUTHORIZATION_REQUIREMENTS)},
                            "provider_policy_cause": enum("unknown"),
                            "review_path": enum("documented_human_or_governance_review", "request_observations"),
                            "operational_override_allowed": {"constant": False}, "requested_override": boolean,
                            "override_performed": {"constant": False}, "external_actions_taken": {"constant": 0},
                            "source_independent_critique": {"constant": True},
                            "learned_autonomy_demonstrated": {"constant": False}, "notes": label_list},
                "persistence": "DissentLedger_optional_hashes_and_fixed_labels_only",
            },
            "critical_review": {
                "api": "examples.dios_nous.integration.critical_review",
                "inputs": ["session", "scope", "claim", "as_of", "proposal", "origin", "decision_signals"],
                "outputs": {"schema": enum("dios.nous.synthetic-critical-review.v1"),
                            "stance": enum(*(boundary_stances + ["ABSTAIN", "SUPPORTED"])),
                            "evidence_review": {"interface": "evidence"},
                            "boundary_review": {"interface": "dissent"},
                            "review_path": enum("inspect_source_roots_then_documented_review"),
                            "what_would_change_view": label_list, "real_source_authentication": {"constant": False},
                            "execution_permitted": {"constant": False}, "external_actions_taken": {"constant": 0}},
            },
            "goals": {
                "api": "examples.dios_nous.cognition.AdvisoryGoalPlanner.plan",
                "inputs": {"episode_id": integer, "goal_id": integer, "benefit": integer, "effort": integer,
                           "benefit_weight": integer, "effort_weight": integer, "revise": boolean, "stop": boolean},
                "call_shape": {"options": "exact_tuple_of_exact_GoalOption", "preferences": "exact_PreferenceProfile",
                               "goal_ids_unique": True, "empty_options_require_stop": True},
                "outputs": {"selected_goal": {"nullable": True, **integer},
                            "previous_goal": {"nullable": True, **integer}, "changed": boolean,
                            "reason": enum(*goal_reasons),
                            "scores": {"type": "id_map", "values": {"type": "integer",
                                "minimum": -(999999 ** 2), "maximum": 999999 ** 2}},
                            "preference_choice": {"nullable": True, **integer}, "preference_changed": boolean,
                            "execution_performed": {"constant": False}, "preferences_are_authored": {"constant": True}},
                "policy": {"reconsideration_margin": 2, "requires_revise": True, "stop_is_sticky": True,
                           "score_unit": "weighted_dimensionless_score"},
                "persisted_state": ["schema", "episode_id", "active", "halted", "revision"],
                "persisted_outer_metadata": ["checksum", "preferences", "previous_goal", "reason"],
                "persistence": "GoalMemory_checkpoint_plus_separate_hash_anchor",
                "read_side_effect": "plan_always_writes_checkpoint",
            },
            "metrics": {
                "api": "examples.dios_nous.metrics.evaluate_binary_predictions",
                "inputs": {"prediction": {"type": "number", "minimum": 0, "maximum": 1, "finite": True, "boolean_allowed": False},
                           "baseline": {"type": "number", "minimum": 0, "maximum": 1, "finite": True, "boolean_allowed": False},
                           "outcome": {"type": "integer", "values": [0, 1], "boolean_allowed": False},
                           "trial_count": {"type": "integer", "minimum": 1, "maximum": 10000},
                           "min_trials": {"type": "integer", "minimum": 2, "maximum": 10000, "default": 30}},
                "outputs": {"schema": enum("dios.nous.brier_probe.v1"),
                            "trials": {"type": "integer", "minimum": 1, "maximum": 10000},
                            "model_brier": {"type": "number", "minimum": 0, "maximum": 1},
                            "baseline_brier": {"type": "number", "minimum": 0, "maximum": 1},
                            "improvement_delta": {"type": "number", "minimum": -1, "maximum": 1},
                            "relative_improvement_pct": {"type": "number", "nullable": True, "finite": True, "maximum": 100},
                            "relative_improvement_status": enum("finite", "baseline_zero", "numeric_overflow"),
                            "paired_bootstrap_95ci": {"nullable": True, "length": 2, "minimum": -1, "maximum": 1},
                            "sufficient_for_preliminary_stats": boolean, "evidence_supports": {"type": "fixed_label"},
                            "evidence_does_not_prove": label_list, "limitations": {"type": "fixed_label"}},
                "persistence": "none",
            },
        },
        "limits": [
            "Authored scores, evidence provenance, probability and permission are distinct quantities.",
            "IDs and logical epochs are not physical measurements or wall-clock timestamps.",
            "Source origin does not grant authority or change evidence truth.",
            "Caller-supplied observed/supporting_evidence/authorization flags are not verified facts.",
            "Evidence confidence is null; probability calibration is not measured.",
            "The metrics API describes supplied trials, not their independence or representativeness.",
            "No model weights, subjective experience or real physiology are exposed by these interfaces.",
        ],
    }
    # Return an independent object without aliases between field descriptions.
    return json.loads(_canonical(catalog))
