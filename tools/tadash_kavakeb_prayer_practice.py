#!/usr/bin/env python3
"""Bounded, offline prayer-cue practice on the unchanged V06 posture engine.

Prayer is display text. Only the explicitly validated simulation schedule is
read by the target adapter. Native integration, support, reflex, rest, force,
resource and gas logic remain responsible for all physical state changes.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
BODY_REL = Path("runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06")
BODY = REPO / BODY_REL
sys.path.insert(0, str(BODY))
from posture_step import PostureLoop, GaitEnvironment, Inputs, norm  # noqa: E402
from contacts import point_margin  # noqa: E402
from run_balance_checks import GasAudit, PhysicsAudit  # noqa: E402
from resource_audit_v06 import ConservationAudit  # noqa: E402

UPSTREAM_COMMIT = "f587e4294776447778758ced539e5da2824359f8"
DEFAULT_CONFIG = REPO / "docs/rituals/kavakeb_prayer_practice_v01.json"
STAGES = ("observe", "geometry", "revise")
MAX_REFERENCE_M = .001
MAX_COM_EXCURSION_M = .005
MAX_COM_SPEED_M_S = .01
NATIVE_SHA256 = {
    "contacts.py": "12eda407e4718bdef844cd81259d95ad321ed87d7733746f2264666bf65646e6",
    "contact_design_v06.json": "f92436e77bc1b5fe4449cb94bbefd9e3c8624fc14d4719458bf10d8ddb191a6a",
    "posture_step.py": "02b845bc9184dd62b8ab17c4661bd17e7ea8e340e2022f4c47428ce748531c06",
    "baseline/motion/sections.py": "1f10a05e6f144a5568599b37e44978c3954e48d4c8ff9d44976dcd92cc2b7141",
    "baseline/pain/pain.py": "d5fa304fd73d4359c02a753fa225c46112aff156d37191f91c7ed42f94b8e60a",
    "baseline/pain/regions.json": "0ddcca51b93a3c54388b9865251fd01fee9e9b432a8ffedba1e8ccad474f9dae",
    "bilateral_sections.py": "e998f091615cac6ae996c0d6276da32a8a9c2a5a3e633eaa2810fb1c1519afbc",
    "body_loop_v06.py": "214f5abf09c634ed3d3935043e40711d513c8980200eb97591ca4fbb70574e2c",
    "breath_motion_v06.py": "76f45f733f80fc021950395ec123079fe6f6c55d7f63e911b0d698a51dad23a1",
    "hydraulic_table_v03.json": "97cb0945ef5f9a08f1e2ce4cfb91d08849ddb2130cc99d6cf43009a090f29c88",
    "pain_resilience_v04.py": "6fd130ba928b1404f2b32107c6528d2c0750eb73924b9e400577ea40451ef54f",
    "resource_audit_v06.py": "d4dac28a30cc827f3dea90004da09f1a81ec51b4e3f2de5bb46aecdb80bd7d23",
    "run_balance_checks.py": "707eb2f5b8bf40bf15a2dfcbe23ee62a9d8001b40527d4b865740fdf2a30086c",
}
PHENOTYPE_SHA256 = "2dc8906c57de807f7adfeebdae21d2f3049accc75b4a65f5effafd127e6e3d37"


def finite_number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: finite number required")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name}: must be finite and in [{low}, {high}]")
    return float(value)


@dataclass(frozen=True)
class Schedule:
    repetitions: int
    duration: float
    dt: float
    amplitude: float
    directions: tuple
    friction: tuple

    @property
    def stage_steps(self):
        return round(self.duration / self.dt)

    @property
    def steps(self):
        return self.repetitions * len(STAGES) * self.stage_steps

    def interval(self, index):
        """Label the executed integration interval, including its endpoint."""
        index = min(max(0, index), self.steps - 1)
        group, within = divmod(index, self.stage_steps)
        return group // 3 + 1, STAGES[group % 3], (within + 1) * self.dt

    def offset_at(self, time_s):
        finite_number(time_s, "simulation time", 0, self.steps * self.dt + 1e-8)
        if time_s >= self.steps * self.dt - 1e-10:
            return [0., 0.]
        # The native floating clock is not rewritten. The small tolerance only
        # assigns boundaries consistently after repeated dt additions.
        group = int((time_s + 1e-10) / self.duration)
        if group % 3 != 1:
            return [0., 0.]
        u = min(1., max(0., (time_s - group * self.duration) / self.duration))
        scale = self.amplitude * math.sin(math.pi * u) ** 2
        return [scale * x for x in self.directions[group // 3]]


def validate_config(config):
    """Small task-specific envelope; a config cannot relax these limits."""
    if config.get("schema") != "nasuraya/kavakeb-prayer-practice/1":
        raise ValueError("unknown practice config schema")
    s = config["simulation"]
    n = s["repetitions"]
    if type(n) is not int or not 1 <= n <= 3:
        raise ValueError("repetitions: integer from 1 to 3 required")
    dt = finite_number(s["dt_s"], "dt_s", .05, .1)
    duration = finite_number(s["stage_duration_s"], "stage_duration_s", dt, 4.)
    if not math.isclose(duration / dt, round(duration / dt), abs_tol=1e-10):
        raise ValueError("stage_duration_s must contain an integer number of steps")
    amplitude = finite_number(s["reference_amplitude_m"], "reference_amplitude_m", 0., MAX_REFERENCE_M)
    if s["stage_order"] != list(STAGES) or s["native_command"] != "stand":
        raise ValueError("only observe/geometry/revise with native stand is supported")
    if s["profile"] != "sin_squared_single_bounded_excursion_during_geometry":
        raise ValueError("unsupported reference profile")
    directions = s["geometry_directions"]
    if not isinstance(directions, list) or len(directions) != n:
        raise ValueError("one finite unit direction is required per round")
    parsed = []
    for i, direction in enumerate(directions):
        if not isinstance(direction, (list, tuple)) or len(direction) != 2:
            raise ValueError("direction must contain exactly two coordinates")
        v = tuple(finite_number(x, f"direction {i}", -1., 1.) for x in direction)
        if not math.isclose(norm(v), 1., rel_tol=0., abs_tol=1e-12):
            raise ValueError("direction must be a unit vector; amplification is forbidden")
        parsed.append(v)
    if s["body_fixture_mass_kg"] != 195:
        raise ValueError("this runner is pinned to the native 195 kg fixture")
    if set(s["friction"]) != {"L", "R"}:
        raise ValueError("bilateral friction is required")
    friction = tuple(finite_number(s["friction"][side], f"friction {side}", .6, .6) for side in ("L", "R"))
    a = config["acceptance"]
    for key in ("native_model_valid", "no_mechanical_termination", "all_pose_reachable", "native_resource_gas_physics_audits"):
        if a[key] is not True:
            raise ValueError(f"{key} cannot be disabled")
    for key, low, high in (
        ("planted_feet_max_drift_m", 0., 1e-9),
        ("minimum_capture_margin_m", .008, .093),
        ("minimum_joint_support_fraction", .999, 1.),
        ("maximum_pressure_kpa", 0., 300.),
        ("maximum_segment_error_m", 0., 1e-8),
        ("maximum_final_center_error_m", 0., .0001),
        ("maximum_final_speed_m_s", 0., .0001),
    ):
        finite_number(a[key], key, low, high)
    bounds = config["bounds"]
    if bounds["execution"] != "isolated_offline_numerical_simulation":
        raise ValueError("only isolated offline execution is supported")
    for key in ("scripture_actuator_authority", "articulated_hands", "spoken_recitation", "live_body_state", "mastery_credit"):
        if bounds[key] is not False:
            raise ValueError(f"{key}: unsupported authority/capability")
    # Deliberately do not inspect prayer text when deriving numeric controls.
    return Schedule(n, duration, dt, amplitude, tuple(parsed), friction)


class PrayerPostureLoop(PostureLoop):
    def __init__(self, schedule, **kwargs):
        super().__init__(**kwargs)
        self.schedule = schedule
        self.last_authored_offset = [0., 0.]
        self.last_reference_guard = None

    def _target(self, e):
        target = super()._target(e)
        s = self.state
        self.last_authored_offset = [0., 0.]
        self.last_reference_guard = None
        if e.command != "stand" or s.phase != "double_support" or s.swing is not None:
            self.last_reference_guard = "native_stance_or_swing"
        elif s.reflex_recovery:
            self.last_reference_guard = "native_reflex"
        elif self._pending_rest(e):
            self.last_reference_guard = "native_pending_rest"
        if self.last_reference_guard:
            return target
        offset = self.schedule.offset_at(s.time_s)
        if len(offset) != 2 or any(not math.isfinite(x) for x in offset) or norm(offset) > MAX_REFERENCE_M + 1e-15:
            raise ValueError("authored reference exceeded the finite 1 mm envelope")
        self.last_authored_offset = list(offset)
        return [target[k] + offset[k] for k in range(2)]


def environment(schedule):
    return GaitEnvironment(body=Inputs(dt_s=schedule.dt), command="stand",
                           friction=dict(zip(("L", "R"), schedule.friction)))


def patch_rows(contact):
    return [{**deepcopy(p), "normal_N": contact["normal_N"][p["id"]],
             "pressure_kpa": contact["pressure_kpa"][p["id"]]} for p in contact["patches"]]


def initial_snapshot(loop):
    p = asdict(loop.state)
    c = loop.contact.solve(p["feet_m"], loop._active(), loop._capture(), loop.weight)
    return {
        "t_s": p["time_s"], "round": 1, "stage": "observe", "stage_elapsed_s": 0.,
        "frame_kind": "initial_static_snapshot", "target_offset_m": [0., 0.],
        "com_m": p["com_m"], "velocity_m_s": p["velocity_m_s"],
        "capture_margin_m": point_margin(c["polygon"], loop._capture()),
        "max_pressure_kpa": max(c["pressure_kpa"].values(), default=0.),
        "phase": p["phase"], "feet_m": p["feet_m"], "kinematics": loop._pose(),
        "tail_angle_rad": p["tail_angle_rad"], "patches": patch_rows(c),
        "contact": c, "passed": c["feasible"],
        "audit_status": "static snapshot; no integrated resource/gas audit frame",
    }


def frame_record(f, schedule, index, offset, initial_feet, center):
    p, c, b = f["posture"], f["contact"], f["balance"]
    repetition, stage, elapsed = schedule.interval(index)
    return {
        "t_s": f["t_s"], "round": repetition, "stage": stage, "stage_elapsed_s": elapsed,
        "frame_kind": "native_integration", "command_t_s": f["t_s"] - schedule.dt,
        "target_offset_m": list(offset), "target_com_m": deepcopy(p["target_com_m"]),
        "reference_com_m": deepcopy(p["reference_com_m"]),
        "com_m": deepcopy(p["com_m"]), "velocity_m_s": deepcopy(p["velocity_m_s"]),
        "capture_margin_m": b["capture_margin_m"],
        "max_pressure_kpa": max(c["pressure_kpa"].values(), default=0.),
        "phase": p["phase"], "feet_m": deepcopy(p["feet_m"]),
        "kinematics": deepcopy(p["kinematics"]), "tail_angle_rad": deepcopy(p["tail_angle_rad"]),
        "patches": patch_rows(c), "contact": deepcopy(c), "balance": deepcopy(b),
        "model_valid": b["model_valid"], "mechanical_simulation_terminated": p["mechanical_simulation_terminated"],
        "native_failed_reason": p["failed_reason"], "events": deepcopy(p["events_this_frame"]),
        "support_fraction": c["joint_support_fraction"],
        "feet_drift_m": max(norm([p["feet_m"][side][k] - initial_feet[side][k] for k in range(3)]) for side in ("L", "R")),
        "com_error_from_center_m": norm([p["com_m"][k] - center[k] for k in range(2)]),
        "com_speed_m_s": norm(p["velocity_m_s"]),
        "all_pose_reachable": all(v["reachable"] for v in p["kinematics"].values()),
        "max_segment_error_m": max(v["segment_length_error_m"] for v in p["kinematics"].values()),
        "ledger": deepcopy(f["ledger"]), "gas": deepcopy(f["respiration"]),
        "body_state": deepcopy(f["state"]),
        "optional_pause_executed": f["task"]["nonessential_pause_executed"],
    }


def frame_failures(row, acceptance, loop, e):
    checks = {
        "native_mechanical_failure": row["model_valid"] and not row["mechanical_simulation_terminated"],
        "planted_feet_drift": row["feet_drift_m"] <= acceptance["planted_feet_max_drift_m"],
        "capture_margin": row["capture_margin_m"] >= acceptance["minimum_capture_margin_m"],
        "joint_support": row["support_fraction"] >= acceptance["minimum_joint_support_fraction"],
        "pressure": row["max_pressure_kpa"] <= acceptance["maximum_pressure_kpa"],
        "leg_reach": row["all_pose_reachable"],
        "segment_length": row["max_segment_error_m"] <= acceptance["maximum_segment_error_m"],
        "com_excursion": row["com_error_from_center_m"] <= MAX_COM_EXCURSION_M,
        "com_speed": row["com_speed_m_s"] <= MAX_COM_SPEED_M_S,
        "native_stance_takeover": row["phase"] == "double_support" and loop.state.swing is None,
        "native_reflex_takeover": not loop.state.reflex_recovery,
        "native_rest_takeover": not loop._pending_rest(e) and not row["optional_pause_executed"],
        "contact_feasible": row["contact"]["feasible"],
        "friction_saturated": not row["contact"]["friction_saturated"],
    }
    return [key for key, passed in checks.items() if not passed]


def run_one(config, kind, *, max_steps=None, environment_factory=None):
    """One isolated continuous run. Injection hooks are for short boundary tests."""
    if not __debug__:
        raise RuntimeError("native audit assertions require Python without -O")
    schedule = validate_config(config)
    if kind not in ("baseline", "practice"):
        raise ValueError("unknown run kind")
    loop = PostureLoop() if kind == "baseline" else PrayerPostureLoop(schedule)
    initial_feet = deepcopy(loop.state.feet_m)
    center = loop._mean_feet()
    audits = {"resource": ConservationAudit(asdict(loop.body.state)),
              "gas": GasAudit(loop), "physics": PhysicsAudit(loop)}
    audit_errors = {}
    rows = [initial_snapshot(loop)]
    failures = []
    stage_counts = [{stage: 0 for stage in STAGES} for _ in range(schedule.repetitions)]
    rounds = []
    limit = schedule.steps if max_steps is None else min(schedule.steps, max_steps)
    if type(limit) is not int or limit < 1:
        raise ValueError("max_steps must be a positive integer")
    for index in range(limit):
        e = environment(schedule) if environment_factory is None else environment_factory(index, loop, schedule)
        try:
            f = loop.step(e)
        except (ValueError, AssertionError, ArithmeticError) as exc:
            failures.append({"frame": index + 1, "t_s": loop.state.time_s,
                             "reasons": ["native_step_exception"], "detail": f"{type(exc).__name__}: {exc}"})
            break
        offset = loop.last_authored_offset if kind == "practice" else [0., 0.]
        row = frame_record(f, schedule, index, offset, initial_feet, center)
        reasons = frame_failures(row, config["acceptance"], loop, e)
        for name, audit in audits.items():
            try:
                audit.frame(f, e) if name == "physics" else audit.frame(f)
            except (AssertionError, ValueError, ArithmeticError) as exc:
                audit_errors[name] = f"{type(exc).__name__}: {exc}"
                reasons.append(f"{name}_audit")
            if not audit.result().get("passed", False):
                audit_errors.setdefault(name, "native audit returned a false verdict")
                if f"{name}_audit" not in reasons:
                    reasons.append(f"{name}_audit")
        row["audits"] = {name: {**audit.result(), "passed": bool(audit.result().get("passed", False) and name not in audit_errors)}
                         for name, audit in audits.items()}
        boundary = (index + 1) % (3 * schedule.stage_steps) == 0
        if boundary:
            if row["com_error_from_center_m"] > config["acceptance"]["maximum_final_center_error_m"]:
                reasons.append("round_return_center")
            if row["com_speed_m_s"] > config["acceptance"]["maximum_final_speed_m_s"]:
                reasons.append("round_return_speed")
        row["failure_reasons"] = reasons
        row["passed"] = not reasons
        rows.append(row)
        if reasons:
            failures.append({"frame": index + 1, "t_s": f["t_s"], "reasons": reasons,
                             "native_failed_reason": row["native_failed_reason"]})
            break
        stage_counts[row["round"] - 1][row["stage"]] += 1
        if boundary:
            rounds.append({"round": row["round"], "completed": True, "end_t_s": f["t_s"],
                           "stage_passed_frames": dict(stage_counts[row["round"] - 1]),
                           "center_error_m": row["com_error_from_center_m"],
                           "speed_m_s": row["com_speed_m_s"]})
    integrated = rows[1:]
    final = integrated[-1] if integrated else None
    complete = len(integrated) == schedule.steps and not failures and len(rounds) == schedule.repetitions
    session_complete = complete and schedule.repetitions == 3
    results = {name: {**audit.result(), "passed": bool(audit.result().get("passed", False) and name not in audit_errors),
                     **({"error": audit_errors[name]} if name in audit_errors else {})}
               for name, audit in audits.items()}
    # Initial snapshot contributes geometry/contact display only, never pass credit.
    summary = {
        "kind": kind, "completed": session_complete, "schedule_completed": complete,
        "session_complete_under_three_pass_rule": session_complete, "full_passes": len(rounds),
        "expected_passes": schedule.repetitions, "integration_frames": len(integrated),
        "passed_integration_frames": sum(row["passed"] for row in integrated),
        "initial_static_snapshots": 1, "simulated_duration_s": loop.state.time_s,
        "requested_duration_s": schedule.steps * schedule.dt, "dt_s": schedule.dt,
        "failures": failures, "status": ("completed" if session_complete else
            ("stopped_on_failure" if failures else ("partial_session_under_three_pass_rule" if complete else "bounded_test_prefix"))),
        "rounds": rounds, "stage_passed_frames_by_round": stage_counts, "audits": results,
        "final_center_error_m": final["com_error_from_center_m"] if final else None,
        "final_speed_m_s": final["com_speed_m_s"] if final else None,
        "max_pressure_kpa": max((r["max_pressure_kpa"] for r in integrated), default=None),
        "min_capture_margin_m": min((r["capture_margin_m"] for r in integrated), default=None),
        "min_joint_support_fraction": min((r["support_fraction"] for r in integrated), default=None),
        "max_com_displacement_m": max((r["com_error_from_center_m"] for r in integrated), default=None),
        "max_com_speed_m_s": max((r["com_speed_m_s"] for r in integrated), default=None),
        "max_reference_offset_m": max((norm(r["target_offset_m"]) for r in integrated), default=None),
        "max_feet_drift_m": max((r["feet_drift_m"] for r in integrated), default=None),
        "max_segment_error_m": max((r["max_segment_error_m"] for r in integrated), default=None),
        "all_pose_reachable": bool(integrated) and all(r["all_pose_reachable"] for r in integrated),
        "total_motor_energy_J": sum(r["ledger"]["motor_energy_J"] for r in integrated),
        "total_fuel_used_J": sum(r["ledger"]["fuel_used_J"] for r in integrated),
        "final_gas": deepcopy(final["gas"]["state"]) if final else asdict(loop.coupling.gas),
    }
    model = {"mass_kg": loop.design["mass_kg"], "com_height_m": loop.design["com_height_m"],
             "leg_lengths_m": loop.design["leg_lengths_m"], "axes": loop.design["axes"]}
    return {"summary": summary, "frames": rows, "model": model, "checkpoint": loop.checkpoint()}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def provenance(config_path):
    expected = {str(BODY_REL / name): value for name, value in NATIVE_SHA256.items()}
    expected["runtimes/tadash_body/phenotype_v1.json"] = PHENOTYPE_SHA256
    observed = {name: digest(REPO / name) for name in expected}
    mismatches = [name for name in expected if expected[name] != observed[name]]
    if mismatches:
        raise ValueError("native sources differ from pinned upstream: " + ", ".join(mismatches))
    return {"repository": "zurvanproject/zohraya", "upstream_commit": UPSTREAM_COMMIT,
            "upstream_runtime_unchanged": True, "native_files_sha256": observed,
            "runner_path": "tools/tadash_kavakeb_prayer_practice.py", "runner_sha256": digest(Path(__file__)),
            "config_path": str(config_path), "config_sha256": digest(config_path)}


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, required=True, help="new directory; existing results are never overwritten")
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    schedule = validate_config(config)
    sources = provenance(args.config)
    args.output.mkdir(parents=True, exist_ok=False)
    baseline = run_one(config, "baseline")
    practice = run_one(config, "practice")
    passed = (baseline["summary"]["session_complete_under_three_pass_rule"]
              and practice["summary"]["session_complete_under_three_pass_rule"])
    summary = {
        "schema": "nasuraya/kavakeb-prayer-practice-result/1", "passed": passed,
        "source": sources, "model": practice["model"], "acceptance": config["acceptance"],
        "baseline": baseline["summary"], "practice": practice["summary"],
        "comparison": {key + "_practice_minus_baseline": practice["summary"][key] - baseline["summary"][key]
                       for key in ("total_motor_energy_J", "total_fuel_used_J")},
        "assistance": ["native standing feedback and rate-limited reference", "native contact pressure and joint force allocation",
                       "native tail flywheel and reflex/rest guards remain enabled"],
        "limitations": ["reduced constant-height horizontal pendulum and three-link inverse-kinematic legs",
                        "native 195 kg fixture; no visual avatar or articulated hands",
                        "prayer text is a cue only; no scripture-to-force mapping or spoken audio",
                        "offline isolated run; no live body state or mastery credit changed",
                        "initial contact snapshot is static; all subsequent physical positions come from native integration"],
    }
    trace = {"schema": "nasuraya/kavakeb-prayer-practice-trace/1", "dt_s": schedule.dt,
             "model": practice["model"], "prayer": deepcopy(config["prayer"]), "source": sources,
             "time_convention": "Each integrated row labels the interval that ends at t_s; initial row is static. Target offset was applied at command_t_s.",
             "frames": practice["frames"], "baseline_frames": baseline["frames"]}
    checkpoint = {"schema": "nasuraya/kavakeb-prayer-practice-checkpoint/1", "source": sources,
                  "config": config, "practice_completed": practice["summary"]["completed"],
                  "practice_native_checkpoint": practice["checkpoint"], "baseline_native_checkpoint": baseline["checkpoint"]}
    write_json(args.output / "summary.json", summary)
    write_json(args.output / "trace.json", trace)
    write_json(args.output / "final_checkpoint.json", checkpoint)
    if args.audit:
        print(json.dumps({"passed": passed, "output": str(args.output),
                          "baseline": baseline["summary"], "practice": practice["summary"]}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
