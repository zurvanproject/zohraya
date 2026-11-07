"""Measure load-weighted contact-point slip during the six pinned first-touch trials.

One row per millisecond after the settled initialization. At each active ground
contact use the relative material-point velocity of both geoms at the contact
position, expressed in the orthonormal contact frame. The integral of weighted
speed is cumulative sliding exposure, not displacement of a single pad.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import numpy as np


def contact_speed(model, data, contact):
    import mujoco

    jac = np.zeros((3, model.nv))
    velocity = np.zeros(3)
    for geom, sign in ((contact.geom1, -1), (contact.geom2, 1)):
        body = model.geom_bodyid[geom]
        if body:
            mujoco.mj_jac(model, data, jac, None, contact.pos, body)
            velocity += sign * (jac @ data.qvel)
    tangents = contact.frame.reshape(3, 3)[1:]
    return float(np.linalg.norm(tangents @ velocity))


class PawSlip:
    def __init__(self):
        self.rows = []
        self.dt = None

    def sample(self, model, data, native_load):
        import mujoco

        self.dt = float(model.opt.timestep)
        loads = np.zeros(2)
        weighted = np.zeros(2)
        wrench = np.empty(6)
        for index, contact in enumerate(data.contact):
            if 0 not in (contact.geom1, contact.geom2):
                continue
            foot = contact.geom2 if contact.geom1 == 0 else contact.geom1
            name = model.geom(foot).name
            if not name.startswith(("ball_", "toe_pad_")):
                continue
            side = 0 if "_L" in name else 1
            mujoco.mj_contactForce(model, data, index, wrench)
            if wrench[0] > 0:
                loads[side] += wrench[0]
                weighted[side] += wrench[0] * contact_speed(model, data, contact)
        if not np.allclose(loads, native_load, rtol=1e-10, atol=1e-9):
            raise ValueError("Observer and controller normal loads disagree")
        # Missing/unloaded samples stay null, not zero slip.
        speeds = [float(weighted[i] / loads[i]) if loads[i] > 1.0 else None for i in (0, 1)]
        self.rows.append([*loads.tolist(), *speeds])

    def result(self):
        if not self.rows or self.dt is None:
            raise ValueError("No contact samples")
        feet = {}
        for i, side in enumerate(("left", "right")):
            speeds = [row[2+i] for row in self.rows if row[2+i] is not None]
            if not speeds:
                raise ValueError(f"No loaded samples for {side} paw")
            feet[side] = {
                "loaded_samples": len(speeds),
                "mean_loaded_speed_mm_s": float(np.mean(speeds)) * 1000,
                "peak_weighted_speed_mm_s": max(speeds) * 1000,
                "integrated_weighted_speed_mm": sum(speeds) * self.dt * 1000,
            }
        return {"timestep_s": self.dt, "first_sample_after_command_s": self.dt,
                "columns": ["left_normal_N", "right_normal_N", "left_tangent_m_s", "right_tangent_m_s"],
                "feet": feet, "samples": self.rows}


def run(source, output):
    from experiments import tadash_motion_episode as evidence
    from experiments import tadash_weight_shift as shift
    from experiments.tadash_first_touch_practice import TRAIN, TEST

    identity = evidence.source_identity(source)
    if output == source or output.is_relative_to(source):
        raise ValueError("Keep output outside the pinned simulator checkout")
    output.mkdir(parents=True, exist_ok=False)
    observer_path = str(Path(__file__).resolve())
    bootstrap = f"import runpy\nslip_observer = runpy.run_path({observer_path!r})['PawSlip']()\n"
    results = []
    for name, target, friction in (*TRAIN, *TEST):
        proc = subprocess.run([sys.executable, "-c", bootstrap + shift.NATIVE, str(target), str(friction)],
                              cwd=source, env=evidence.clean_env(), capture_output=True,
                              text=True, timeout=240)
        if proc.returncode:
            raise RuntimeError(proc.stderr[-4000:])
        raw = json.loads(proc.stdout)
        evidence.write(output / f"{name}.json", raw)
        shift.validate(raw, target)
        slip = raw["paw_slip"]
        if (raw["friction"] != friction or len(slip["samples"]) != 4000 or slip["timestep_s"] != .001
                or abs(raw["returned_com_y_delta_m"]) >= .0001):
            raise ValueError("Unexpected physical configuration, coverage or return")
        results.append({"name": name, "shift_m": target, "friction": friction,
                        "source_trace_sha256": evidence.sha(output / f"{name}.json"),
                        "feet": slip["feet"]})
    summary = {"schema": "tadash-native-paw-slip/1", "source": identity, "trials": results}
    evidence.write(output / "summary.json", summary)
    print(json.dumps(summary, allow_nan=False))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--motion-source", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    run(args.motion_source.resolve(), args.output.resolve())
