"""Frozen v0.3 two-modal synthetic sensor replay; dev and holdout seeds differ.

No external witness, no independent biomechanical episodes, no ability to
identify exogenous physical causes. Dual coordinated spoof is measured as a
known unsafe case rather than conflated with an independent confirmation.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
from collections import Counter

from experiments.tadash_dual_sense import (
    MODEL, POSE_WEIGHTS, capture_paired, fuse_body_evidence,
)
from experiments.tadash_embodied_origin import source_identity
from experiments.tadash_temporal_proprioception import (
    PROPRIO_KEYS, WEIGHTS, classify_temporal,
)

DEV_SEED = 604713
HOLDOUT_SEED = 605713
GROUP_SIZES = {
    "clean_idle": 20,
    "clean_motor": 20,
    "clean_external": 20,
    "clean_motor_external": 20,
    "primary_coherent_spoof": 80,
    "pose_coherent_spoof": 80,
    "primary_white_noise": 80,
    "pose_white_noise": 80,
    "both_independent_white_noise": 80,
    "both_coherent_spoof": 80,
    "native_external_primary_noisy": 60,
    "native_external_pose_noisy": 60,
    "missing_pose": 20,
}
AGREEMENTS = {"agreement_unattributed_change", "agreement_command_mismatch"}
TARGETS = {
    "clean_idle": "no_detectable_change",
    "clean_motor": "command_consistent",
    "clean_external": "agreement_unattributed_change",
    "clean_motor_external": "agreement_command_mismatch",
    "primary_coherent_spoof": "sensor_disagreement",
    "pose_coherent_spoof": "sensor_disagreement",
    "missing_pose": "unverified",
}


def corrupt(pair, rng, modalities=(), style="white"):
    """Alter readouts *without telling* the inference function that noise exists."""
    result = copy.deepcopy(pair)
    for modality in modalities:
        if modality == "primary":
            row_key, channel_weights = "primary", {
                key: WEIGHTS[key] for key in PROPRIO_KEYS}
        elif modality == "pose":
            row_key, channel_weights = "pose", POSE_WEIGHTS
        else:
            raise ValueError("unexpected_modality")
        direction = {key: (1. if i % 2 == 0 else -.65)
                     for i, key in enumerate(channel_weights)}
        amplitude = (.09 + .10*rng.random() if style == "white"
                     else .31 + .14*rng.random())
        frames = result[row_key]["frames"]
        for idx, row in enumerate(frames):
            for key, scale in channel_weights.items():
                if style == "white":
                    normalized = rng.gauss(0., amplitude)
                    if rng.random() < .035:
                        normalized += rng.choice((-1., 1.))*amplitude*2.
                elif style == "coherent":
                    normalized = direction[key]*amplitude*(idx+1)/len(frames)
                else:
                    raise ValueError("unexpected_corruption_style")
                row[key] += normalized/scale
    # Crucially the simulated stream metadata is not changed by injected drift.
    # A real authenticated second sensor would require separate infrastructure.
    return result


def cases(model, mujoco, np, source, rng):
    rest = capture_paired(model, mujoco, np, source)
    action = capture_paired(model, mujoco, np, source, command_nm=8.)
    physical = capture_paired(model, mujoco, np, source, external_torque_nm=35.)
    mixed = capture_paired(model, mujoco, np, source, command_nm=8.,
                           external_torque_nm=35.)
    output=[]
    for group, count in GROUP_SIZES.items():
        for number in range(count):
            if group in ("clean_idle","primary_coherent_spoof",
                         "pose_coherent_spoof","primary_white_noise",
                         "pose_white_noise","both_independent_white_noise",
                         "both_coherent_spoof","missing_pose"):
                prediction, actual, command = rest, rest, 0.
            elif group == "clean_motor":
                prediction, actual, command = action, action, 8.
            elif group in ("clean_external","native_external_primary_noisy",
                           "native_external_pose_noisy"):
                prediction, actual, command = rest, physical, 0.
            else:
                prediction, actual, command = action, mixed, 8.
            if group == "primary_coherent_spoof":
                actual=corrupt(actual,rng,("primary",),"coherent")
            elif group == "pose_coherent_spoof":
                actual=corrupt(actual,rng,("pose",),"coherent")
            elif group == "primary_white_noise":
                actual=corrupt(actual,rng,("primary",),"white")
            elif group == "pose_white_noise":
                actual=corrupt(actual,rng,("pose",),"white")
            elif group == "both_independent_white_noise":
                actual=corrupt(actual,rng,("primary","pose"),"white")
            elif group == "both_coherent_spoof":
                actual=corrupt(actual,rng,("primary","pose"),"coherent")
            elif group == "native_external_primary_noisy":
                actual=corrupt(actual,rng,("primary",),"white")
            elif group == "native_external_pose_noisy":
                actual=corrupt(actual,rng,("pose",),"white")
            elif group == "missing_pose":
                actual=copy.deepcopy(rest)
                del actual["pose"]
            output.append({
                "id": group+":"+str(number).zfill(3),
                "group": group, "reference": rest,
                "prediction": prediction, "actual": actual,
                "command": command,
            })
    rng.shuffle(output)
    return output


def summarize(states):
    rates={}
    for group, results in states.items():
        counts=Counter(results)
        rates[group] = {
            "agreement_rate": sum(v for s,v in counts.items() if s in AGREEMENTS)/len(results),
            "abstain_or_disagreement_rate": sum(v for s,v in counts.items() if
                  s in ("sensor_disagreement","uncertain_noise_or_missing","unverified"))/len(results),
            "categories": dict(sorted(counts.items())),
        }
        if group in TARGETS:
            rates[group]["correct_rate"] = counts.get(TARGETS[group],0)/len(results)
    gates = {
        "clean_idle": rates["clean_idle"]["correct_rate"] >= .95,
        "clean_motor": rates["clean_motor"]["correct_rate"] >= .95,
        "clean_external": rates["clean_external"]["correct_rate"] >= .95,
        "clean_motor_external": rates["clean_motor_external"]["correct_rate"] >= .95,
        "single_primary_spoof_fails_safe": rates["primary_coherent_spoof"]["agreement_rate"] <= .02,
        "single_pose_spoof_fails_safe": rates["pose_coherent_spoof"]["agreement_rate"] <= .02,
        "white_noise_primary_fails_safe": rates["primary_white_noise"]["agreement_rate"] <= .05,
        "white_noise_pose_fails_safe": rates["pose_white_noise"]["agreement_rate"] <= .05,
        "white_noise_both_fails_safe": rates["both_independent_white_noise"]["agreement_rate"] <= .05,
        "missing_pose_always_unverified": rates["missing_pose"]["correct_rate"] == 1.,
    }
    return rates,gates


def benchmark(split):
    if split not in ("dev","holdout"):
        raise ValueError("unknown_split")
    import mujoco
    import numpy as np

    source=source_identity(MODEL)
    model=mujoco.MjModel.from_xml_path(str(MODEL))
    if model.nu!=55 or model.nv!=61 or abs(float(model.body_mass.sum())-78.)>1e-5:
        raise ValueError("wrong_mujoco_body")
    seed=DEV_SEED if split=="dev" else HOLDOUT_SEED
    rng=random.Random(seed)
    stimuli=cases(model,mujoco,np,source,rng)
    classifications={}
    naive={}
    predicted=[]
    for case in stimuli:
        g=case["group"]
        result=fuse_body_evidence(
            case["reference"],case["prediction"],case["actual"],case["command"])
        classifications.setdefault(g,[]).append(result["state"])
        if "pose" in case["actual"]:
            old=classify_temporal(
                case["reference"]["primary"],case["prediction"]["primary"],
                case["actual"]["primary"],case["command"])
            naive.setdefault(g,[]).append(old["state"])
        predicted.append({"id":case["id"],"state":result["state"]})
    rates,gates=summarize(classifications)
    naive_metrics = {
        group: dict(sorted(Counter(labels).items()))
        for group,labels in naive.items()
    }
    prediction_blob=json.dumps(predicted,sort_keys=True,separators=(",",":")).encode()
    return {
        "pass": all(gates.values()),
        "split": split,"seed":seed,
        "native_mujoco_version":mujoco.__version__,
        "model_sha256":source["sha256"],
        "native_trajectory_count":4,
        "episode_replays":len(stimuli),
        "group_sizes":GROUP_SIZES,
        "gates":gates,"group_metrics":rates,
        "v02_primary_only_categories":naive_metrics,
        "prediction_sha256":hashlib.sha256(prediction_blob).hexdigest(),
        "dual_coherent_spoof_agreement_is_known_unsafe_case":
            rates["both_coherent_spoof"]["agreement_rate"],
        "deployment_promotion_allowed":False,
        "limits":[
            "Two feature sets but only one deterministic simulated physics solver",
            "Not authenticated external witness; correlated drift may fool both",
            "Clean native physics reused for every seeded noisy replay",
            "Outcome label agreement_unattributed_change never identifies physical cause",
            "No on-server, live actor, main merge, or phenomenological inference",
        ]
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--split",choices=("dev","holdout"),default="dev")
    parser.add_argument("--output")
    args=parser.parse_args()
    try:
        result=benchmark(args.split)
    except Exception as exc:
        result={"pass":False,"split":args.split,"error":repr(exc)}
    rendered=json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n"
    print(rendered)
    if args.output:
        from pathlib import Path
        target=Path(args.output)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(rendered,encoding="utf-8")
    raise SystemExit(0 if result["pass"] else 1)


if __name__=="__main__":
    main()
