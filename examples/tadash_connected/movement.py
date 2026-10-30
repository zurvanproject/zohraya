"""GMR and Mink kinematic landmark targets, followed by a real MyoSuite elbow."""
from contextlib import redirect_stdout
from io import StringIO

import mink
import mujoco
import numpy as np
from myosuite import make_env
from myosuite.core.config import EnvConfig
from myosuite.envs.wrappers import FatigueWrapper

from .gmr_core.motion_retarget import GeneralMotionRetargeting

LANDMARKS = {"Hips": "pelvis", "Spine": "torso", "RightForeArm": "forearm_R",
             "RightHand": "hand_R", "LeftFoot": "foot_L", "RightFoot": "foot_R"}


class ArmTargets:
    def __init__(self):
        with redirect_stdout(StringIO()):
            self.solver = GeneralMotionRetargeting("calibration", "nasuraya_v03", verbose=False)
        model = self.solver.model
        # Upstream's default velocity dictionary uses actuator names. This
        # atlas uses e.g. elbow_R_motor for the actuator and elbow_R for the joint.
        limits = {model.joint(i).name: 2.5 for i in range(model.njnt)
                  if model.jnt_type[i] == mujoco.mjtJoint.mjJNT_HINGE}
        self.solver.ik_limits.append(mink.VelocityLimit(model, limits))
        self.reference = mujoco.MjData(model)
        self.elbow = int(model.joint("elbow_R").qposadr[0])
        self.mass_kg = float(mujoco.mj_getTotalmass(model))
        if abs(self.mass_kg - 78.) > .02:
            raise ValueError("Unexpected v03 atlas mass")

    def retarget(self, selected):
        # A reproducible authored gesture in human-labelled landmarks. External
        # motion capture can supply the same world positions and WXYZ quaternions.
        goal = {"walk": .36, "observe": .07}.get(selected, 0.)
        self.reference.qpos[self.elbow] = goal
        mujoco.mj_forward(self.solver.model, self.reference)
        frame = {human: (self.reference.body(name).xpos.copy(),
                         self.reference.body(name).xquat.copy())
                 for human, name in LANDMARKS.items()}
        for _ in range(12):
            qpos = self.solver.retarget(dict(frame))
        data = self.solver.configuration.data
        hand_error = float(np.linalg.norm(data.body("hand_R").xpos - frame["RightHand"][0]))
        return {"target_elbow_rad": goal, "solved_elbow_rad": float(qpos[self.elbow]),
                "hand_target_error_m": hand_error, "qpos": qpos.tolist()}


class MuscleArm:
    """Upstream six-muscle elbow fixture coupled to the selected native action."""

    def __init__(self, initial_fatigue, seconds, *, seed=17):
        feature = (FatigueWrapper, {"fatigue_reset_vec": np.full(6, initial_fatigue)})
        cfg = EnvConfig("myoElbowPose1D6MRandom-v0", features=(feature,),
                        max_episode_steps=100 * seconds + 1)
        self.env = make_env(cfg)
        self.env.reset(seed=seed)
        self.fatigue = self.env.get_wrapper_attr("muscle_fatigue")
        self.dt = float(self.env.unwrapped.dt)
        self.steps_per_second = round(1. / self.dt)
        if abs(self.steps_per_second * self.dt - 1.) > 1e-8:
            raise ValueError("MyoSuite control steps must divide one simulated second")
        model = self.env.unwrapped.model
        self.names = [model.actuator(i).name for i in range(model.nu)]
        self.flexor = np.array([name.lower().startswith(("bic", "bra")) for name in self.names])
        if self.flexor.sum() != 3 or len(self.names) != 6:
            raise ValueError("Unexpected MyoSuite elbow actuator map")

    def measure(self):
        return {"mean_fatigue": float(self.fatigue.MF.mean()),
                "mean_active": float(self.fatigue.MA.mean()),
                "elbow_rad": float(self.env.unwrapped.data.qpos[0]),
                "time_s": float(self.env.unwrapped.data.time),
                "compartments": self.fatigue.state_dict()}

    def advance(self, selected, solved_elbow):
        signal = np.full(6, -1., dtype=np.float32)
        if selected in ("walk", "observe"):
            # Map the kinematic excursion to an authored biceps/brachialis
            # excitation. This reference elbow has its own physical parameters.
            signal[self.flexor] = np.clip(-1. + 5.0 * max(0., solved_elbow), -1., 1.)
        before = float(self.env.unwrapped.data.time)
        for _ in range(self.steps_per_second):
            _, _, terminated, truncated, _ = self.env.step(signal)
            if terminated or truncated:
                raise RuntimeError("MyoSuite episode ended before paired cycle completed")
        result = self.measure()
        if abs(result["time_s"] - before - 1.) > 1e-7:
            raise RuntimeError("MyoSuite and Tadash time increments disagree")
        error = np.max(np.abs(self.fatigue.MA + self.fatigue.MR + self.fatigue.MF - 1.))
        if not np.isfinite(error) or error > 1e-5:
            raise RuntimeError("Invalid MyoSuite muscle compartments")
        result["control_steps"] = self.steps_per_second
        result["max_compartment_error"] = float(error)
        return result

    def close(self):
        self.env.close()
