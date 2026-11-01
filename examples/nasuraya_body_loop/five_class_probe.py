"""Prospectively frozen, 24-cycle five-action Tadash shadow experiment.

Separate from the stage-3 autonomous one-shot governor. Running this command
requires an explicit invocation. No outputs update the model, the native body,
the original training, or action selection. Scenarios are targeted synthetic
stressors, NOT independent blind evidence.
"""
from __future__ import annotations

from copy import deepcopy
import itertools
import json
import math
from pathlib import Path
import tempfile

from reflection_cycle import digest
from synthetic_fixture import prepare_defaults, synthetic_origin
from .experience import context, metrics
from .host import executed_body
from .rare_action_probe import (
    EXPECTED_TRAINING, append, frozen_training, modified_body,
    put, read_strict, session,
)
from .five_class_metacognition import LABELS, forecast_five, score_five

SCHEMA = "nasuraya-stage3-five-class-native-probe/1"
CASES = tuple(dict(
    id=f"meta5-{i:02}", fatigue=fatigue, sleep_pressure=sleep, pain=pain,
    preferred="walk", duration_s=(.1 if pain < .15 else .3),
) for i, (fatigue, sleep, pain) in enumerate(itertools.product(
    (.485, .525, .555, .585), (.37, .56, .74), (.12, .22)), 1))


def protocol():
    raw = dict(
        schema=SCHEMA, cases=list(CASES), expected_training=EXPECTED_TRAINING,
        prediction_labels=list(LABELS), laplace_alpha=1,
        run_kind="explicit offline synthetic native probe",
        independent_blind_holdout=False, model_updates_allowed=False,
        authority="read-only shadow forecast; no software or physical action authority",
    )
    return dict(raw, protocol_sha256=digest(raw))


def jsonlines(path):
    def unique(pairs):
        obj = {}
        for k, v in pairs:
            if k in obj:
                raise ValueError("duplicate JSONL key")
            obj[k] = v
        return obj
    return [json.loads(line, object_pairs_hook=unique,
                       parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
            for line in path.read_text(encoding="utf-8").splitlines()]


def validate(output_dir):
    """Rebuild every frozen prediction and outcome score from stored training."""
    output = Path(output_dir)
    if read_strict(output / "protocol.json") != protocol():
        raise ValueError("five-action protocol changed")
    training = frozen_training(output / "training.json")
    pre_rows = jsonlines(output / "predictions.jsonl")
    outcomes = jsonlines(output / "outcomes.jsonl")
    if len(pre_rows) != len(outcomes) or len(pre_rows) != len(CASES):
        raise ValueError("missing or extra native cycles")
    scores, actual_counts, covered_counts = [], dict.fromkeys(LABELS, 0), dict.fromkeys(LABELS, 0)
    for case, pre, actual in zip(CASES, pre_rows, outcomes):
        ident = case["id"]
        if pre.get("id") != ident or actual.get("id") != ident or pre.get("case") != case:
            raise ValueError("case order changed")
        if (pre.get("training_sha256") != training["sha256"] or
                pre.get("training_count") != EXPECTED_TRAINING):
            raise ValueError("post-outcome leakage or changed training hash")
        prediction = forecast_five(training["episodes"], context=pre["context"],
                                   preferred=case["preferred"], duration_s=case["duration_s"])
        if prediction != pre.get("forecast"):
            raise ValueError("frozen five-class forecast changed after outcome")
        if actual.get("before_checkpoint_sha256") != pre.get("before_checkpoint_sha256"):
            raise ValueError("native source checkpoint differs from forecast checkpoint")
        source = actual.get("source")
        if not isinstance(source, str) or not source.startswith("native-decision://" + ident + "/"):
            raise ValueError("missing native decision receipt")
        if (actual.get("native_completed_cycles") != 1 or
                actual.get("replayed") is not False or actual.get("scored") is not True):
            raise ValueError("not a new completed native cycle")
        if actual.get("actual_action") not in (
                "walk", "observe", "protect", "slow_breath", "rapid_breath",
                "rest", "cool", "sleep", "other"):
            raise ValueError("unrecognized native action")
        audit = actual.get("body_audit")
        if not isinstance(audit, dict) or any(
            type(audit.get(k)) not in (int, float) or not math.isfinite(audit[k]) or abs(audit[k]) > bound
            for k, bound in (("energy_error_J", 1e-6), ("water_error_L", 1e-8))
        ):
            raise ValueError("native resource conservation failed")
        checked = score_five(prediction, actual["actual_action"], source)
        if checked != actual.get("score"):
            raise ValueError("changed after-outcome score")
        scores.append(checked)
        actual_counts[checked["actual"]] += 1
        if not checked["abstained"]:
            covered_counts[checked["actual"]] += 1

    count = len(scores)
    covered = [s for s in scores if not s["abstained"]]
    rare = actual_counts["slow_breath"]
    rare_hits = sum(s["actual"] == "slow_breath" and
                    s["predicted_action"] == "slow_breath" for s in scores)
    mean = lambda key: sum(s[key] for s in scores) / count
    summary = dict(
        schema=SCHEMA, validation_passed=True,
        protocol_sha256=protocol()["protocol_sha256"], training_sha256=training["sha256"],
        cases=count, native_cycles=count, actual_counts=actual_counts,
        covered_by_actual=covered_counts, abstentions=count - len(covered),
        selective_coverage=len(covered) / count,
        selective_accuracy=(sum(s["correct_when_covered"] for s in covered) / len(covered)
                            if covered else None),
        slow_breath_events=rare, exact_slow_breath_hits=rare_hits,
        exact_slow_breath_recall=(rare_hits / rare if rare else None),
        five_class_brier=mean("brier"),
        pooled_five_class_brier=mean("pooled_brier"),
        lifted_four_class_brier=mean("lifted_four_brier"),
        pooled_minus_five_brier=mean("pooled_brier") - mean("brier"),
        lifted_four_minus_five_brier=mean("lifted_four_brier") - mean("brier"),
        no_holdout_learning=True, model_api_calls=0,
        physical_actuator_calls=0, model_weight_updates=0,
        can_act_autonomously=False, confidence_calibrated=False,
        research_conclusion=(
            "five_class_improved_on_targeted_synthetic_set"
            if mean("brier") < min(mean("pooled_brier"), mean("lifted_four_brier"))
            else "five_class_not_better_than_both_controls"
        ),
        limitations=[
            "Scenarios were authored after the earlier four-class taxonomy limitation was observed.",
            "Read-only shadow forecasts do not alter native or physical action selection.",
            "Brier comparison uses an identical five-category outcome space for every control.",
            "Abstention thresholds are heuristics, not measured calibration or consciousness.",
            "No claim of novel-world generalization, subjective feeling or free will.",
        ],
    )
    if (output / "summary.json").exists() and read_strict(output / "summary.json") != summary:
        raise ValueError("saved summary differs from independent recomputation")
    return summary


def run_probe(output_dir, training_file):
    output = Path(output_dir)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    training = frozen_training(Path(training_file))
    put(output / "protocol.json", protocol())
    put(output / "training.json", training)
    prepare_defaults()
    origin = synthetic_origin()
    for case in CASES:
        body = modified_body(origin, case)
        with tempfile.TemporaryDirectory(prefix=case["id"] + "-", dir=output) as temporary:
            with session(Path(temporary) / "native.sqlite", case, body) as loop:
                snapshot = loop.observe()
                ctx = context(metrics(snapshot))
                frozen = forecast_five(training["episodes"], context=ctx,
                                       preferred=case["preferred"], duration_s=case["duration_s"])
                pre = dict(
                    id=case["id"], case=case, context=ctx,
                    before_checkpoint_sha256=snapshot["checkpoint_sha256"],
                    training_sha256=training["sha256"], training_count=len(training["episodes"]),
                    forecast=frozen,
                )
                append(output / "predictions.jsonl", pre)  # fsync BEFORE native step
                response = loop.step(decision_id=case["id"], duration_s=case["duration_s"],
                                     preferred_action=case["preferred"])
                receipt = loop.engine.get(case["id"])
                if (not executed_body(receipt) or response.get("status") != "complete" or
                        receipt["request"]["evidence"][0]["source_sha256"] !=
                        snapshot["checkpoint_sha256"]):
                    raise RuntimeError("unverified native decision")
                source = "native-decision://" + case["id"] + "/" + digest(receipt)
                score = score_five(frozen, response["actual_action"], source)
                append(output / "outcomes.jsonl", dict(
                    id=case["id"], scored=True, source=source, score=score,
                    actual_action=response["actual_action"],
                    before_checkpoint_sha256=snapshot["checkpoint_sha256"],
                    after_checkpoint_sha256=response["self_model_after"]["checkpoint_sha256"],
                    body_audit=response["body_audit"],
                    native_completed_cycles=loop.status()["completed_cycles"],
                    replayed=response["replayed"],
                ))
    summary = validate(output)
    put(output / "summary.json", summary)
    return validate(output)
