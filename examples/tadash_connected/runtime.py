"""Finite, isolated execution of the coupled controller and measurement loop."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import sys

import numpy as np

from . import CASES
from .movement import ArmTargets, MuscleArm
from .policy import EffortPolicy


def native_template(runtime):
    # The caller supplies an isolated copy. Synthetic defaults are written only there.
    sys.path.insert(0, str(Path(runtime).resolve()))
    from synthetic_fixture import prepare_defaults, synthetic_body
    prepare_defaults()
    return synthetic_body()


def run_case(template, name, cycles, initial_fatigue, missing_first=False, *, arm_seed=17):
    from interoceptive_trends import InteroceptiveBody
    from neuropelvic_body import NeuroPelvicBody
    from persistent_embodiment_v1 import instant

    body = InteroceptiveBody(NeuroPelvicBody(deepcopy(template)))
    policy, targets = EffortPolicy(), ArmTargets()
    arm = MuscleArm(initial_fatigue, cycles, seed=arm_seed)
    rows = []
    try:
        for index in range(cycles):
            before = body.bridge.body.owner.body()["minimum_state"]
            muscle_before = arm.measure()
            decision = policy.decide(before, muscle_before["mean_fatigue"],
                                     missing=missing_first and index == 0)
            at = (instant(body.bridge.body.owner.wall_utc) + timedelta(seconds=1)).isoformat()
            # Feed the measured reference elbow into the next native upper-arm command.
            elbow_target = float(np.clip(muscle_before["elbow_rad"], 0., 1.5))
            event_id = f"{name}-{index + 1:03d}"
            receipt = body.cycle(event_id=event_id, at_utc=at, duration_s=1.,
                expected_revision=body.bridge.revision, requested=decision["requested"],
                external={"native": {"upper_targets": {"elbow_R": elbow_target}}})
            actual = receipt["selected_action"]
            motion = targets.retarget(actual)
            muscle_after = arm.advance(actual, motion["solved_elbow_rad"])
            policy.feedback(actual, muscle_after["mean_fatigue"])
            if not receipt["audit"]["same_owner_ticks"] or receipt["owner_ticks"] != 10:
                raise RuntimeError("Incorrect native owner tick accounting")
            if abs(receipt["audit"]["energy_error_J"]) >= 5e-5 or abs(receipt["audit"]["water_error_L"]) >= 1e-8:
                raise RuntimeError("Native resource audit exceeded tolerance")
            rows.append({"schema": "tadash-connected-cycle/1", "case": name,
                "event_id": event_id, "at_utc": at, "second": index+1,
                "decision": decision, "selected_action": actual, "before_native": before,
                "after_native": receipt["after_body"], "native_ticks": receipt["owner_ticks"],
                "elbow_target_for_native_rad": elbow_target,
                "interoception": receipt["interoception"], "native_audit": receipt["audit"],
                "before_myo": muscle_before, "after_myo": muscle_after,
                "motion": motion, "atlas_mass_kg": targets.mass_kg})
    finally:
        arm.close()
    return rows


if __name__ == "__main__":
    runtime, output, steps = sys.argv[1:]
    template = native_template(runtime)
    rows = []
    for case, fatigue, masked in CASES:
        rows.extend(run_case(template, case, int(steps), fatigue, missing_first=masked))
    Path(output).write_text(json.dumps(rows, allow_nan=False))
