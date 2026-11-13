"""Fail-closed, read-only connectivity audit for the pinned 78 kg v03 MJCF.

Static checks prove parentage/seams and actuator mapping in an authored rigid-body
proxy. Optional native checks prove MuJoCo compilation and kinematic response.
Neither is tissue/anatomy validation, gait certification or a live-body change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "assets/nasuraya_articulated_v03/nasuraya.xml"


def numbers(raw, size):
    try:
        result = tuple(float(s) for s in raw.split())
    except (ValueError, AttributeError):
        return None
    if len(result) != size or not all(math.isfinite(v) for v in result):
        return None
    return result


def distance(a, b):
    if a is None or b is None or len(a) != len(b):
        return math.inf
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def audit_tree(root):
    failures = []
    checks = {}

    def require(label, condition):
        ok = bool(condition)
        checks[label] = ok
        if not ok:
            failures.append(label)

    world = root.find("worldbody")
    if world is None:
        return {"pass": False, "failures": ["worldbody_missing"],
                "checks": {}, "metrics": {}}

    bodies, parents, body_names = {}, {}, []

    def visit(element, parent):
        for body in element.findall("body"):
            name = body.get("name")
            body_names.append(name)
            if name not in bodies:
                bodies[name] = body
                parents[name] = parent
            visit(body, name)

    visit(world, "world")
    require("body_names_unique", len(body_names) == len(set(body_names)))
    require("only_pelvis_world_root", len(world.findall("body")) == 1 and
            parents.get("pelvis") == "world")
    require("one_pelvis_free_root", len(root.findall(".//freejoint")) == 1 and
            bodies.get("pelvis") is not None and
            len(bodies["pelvis"].findall("freejoint")) == 1)

    arcs = [("pelvis", "torso"), ("torso", "head"), ("pelvis", "tail_1")]
    for side in ("L", "R"):
        arcs.extend([
            ("pelvis", "thigh_" + side),
            ("thigh_" + side, "shin_" + side),
            ("shin_" + side, "metatarsal_" + side),
            ("metatarsal_" + side, "foot_" + side),
            ("torso", "upper_arm_" + side),
            ("upper_arm_" + side, "forearm_" + side),
            ("forearm_" + side, "hand_" + side),
        ])
        arcs.extend(("foot_" + side, f"toe_{side}_{i}") for i in range(1, 4))
        arcs.extend(("hand_" + side, f"finger_{side}_{i}") for i in range(1, 6))
    arcs.extend((f"tail_{i-1}", f"tail_{i}") for i in range(2, 5))
    for parent, child in arcs:
        require("parent:" + child, parents.get(child) == parent)
    require("four_tail_links", {name for name in bodies if name.startswith("tail_")} ==
            {f"tail_{i}" for i in range(1, 5)})
    for side in ("L", "R"):
        require("three_toes:" + side,
                {n for n in bodies if n.startswith("toe_" + side + "_")} ==
                {f"toe_{side}_{i}" for i in range(1, 4)})
        require("five_fingers:" + side,
                {n for n in bodies if n.startswith("finger_" + side + "_")} ==
                {f"finger_{side}_{i}" for i in range(1, 6)})

    named_joints = [j for j in root.findall("./worldbody//joint") if j.get("name")]
    joint_names = [j.get("name") for j in named_joints]
    joints = {j.get("name"): j for j in named_joints}
    motors = root.findall("./actuator/motor")
    motor_joints = [m.get("joint") for m in motors]
    require("55_named_joints", len(named_joints) == 55)
    require("unique_joint_names", len(set(joint_names)) == len(joint_names))
    require("55_motors", len(motors) == 55)
    require("motor_joint_bijection", len(set(motor_joints)) == len(motor_joints)
            and set(motor_joints) == set(joint_names))
    for joint in named_joints:
        name = joint.get("name")
        axis = numbers(joint.get("axis"), 3)
        limits = numbers(joint.get("range"), 2)
        require("hinge_axis:" + name, joint.get("type") == "hinge" and
                axis is not None and abs(distance(axis, (0., 0., 0.)) - 1.) < 1e-6)
        require("finite_range:" + name, limits is not None and limits[0] < limits[1])
    for motor in motors:
        name = motor.get("joint") or "unnamed"
        ctrl = numbers(motor.get("ctrlrange"), 2)
        force = numbers(motor.get("forcerange"), 2)
        gear = numbers(motor.get("gear", "1"), 1)
        require("bounded_motor:" + name,
                motor.get("ctrllimited") == "true" and
                motor.get("forcelimited") == "true" and
                ctrl is not None and force is not None and
                ctrl[0] < 0 < ctrl[1] and force[0] < 0 < force[1] and
                gear is not None and gear[0] != 0)

    for side in ("L", "R"):
        for joint in (f"hip_{axis}_{side}" for axis in ("yaw", "roll", "pitch")):
            require("leg_joint:" + joint, joint in joints)
        for name in (f"knee_{side}", f"hock_pitch_{side}",
                     f"hock_roll_{side}", f"mtp_{side}"):
            require("leg_joint:" + name, name in joints)
        for i in range(1, 4):
            toe = bodies.get(f"toe_{side}_{i}")
            require(f"toe_joint:{side}:{i}", toe is not None and
                    len(toe.findall("joint")) == 1 and
                    toe.find("joint").get("name") == f"toe_flex_{side}_{i}")
            require(f"toe_pad:{side}:{i}", toe is not None and
                    toe.find(f"geom[@name='toe_pad_{side}_{i}']") is not None)
        foot = bodies.get("foot_" + side)
        require("ball_on_foot:" + side, foot is not None and
                foot.find(f"geom[@name='ball_{side}']") is not None)
        require("contact_site_on_foot:" + side, foot is not None and
                foot.find(f"site[@name='foot_contact_{side}']") is not None)

    masses = []
    for body in bodies.values():
        require("finite_body_pos:" + str(body.get("name")),
                numbers(body.get("pos", "0 0 0"), 3) is not None)
        for geom in body.findall("geom"):
            mass = numbers(geom.get("mass"), 1)
            require("positive_explicit_geom_mass:" + str(geom.get("name")),
                    mass is not None and mass[0] > 0)
            if mass is not None:
                masses.append(mass[0])
            if geom.get("fromto") is not None:
                endpoints = numbers(geom.get("fromto"), 6)
                require("finite_nonzero_geom_path:" + str(geom.get("name")),
                        endpoints is not None and
                        distance(endpoints[:3], endpoints[3:]) > 0)

    total_mass = sum(masses)
    require("authored_mass_78kg", abs(total_mass - 78.) < 1e-5)

    tail_length = 0.0
    for i in range(1, 5):
        tail = bodies.get(f"tail_{i}")
        geo = tail.find(f"geom[@name='tail_geom_{i}']") if tail is not None else None
        v = numbers(geo.get("fromto"), 6) if geo is not None else None
        require(f"tail_two_joints:{i}", tail is not None and
                {j.get("name") for j in tail.findall("joint")} ==
                {f"tail_yaw_{i}", f"tail_pitch_{i}"})
        if v is not None:
            tail_length += distance(v[:3], v[3:])
        if i < 4:
            nxt = bodies.get(f"tail_{i+1}")
            local_socket = numbers(nxt.get("pos"), 3) if nxt is not None else None
            require(f"tail_link_seam:{i}->{i+1}", v is not None and
                    distance(v[3:], local_socket) < 1e-7)
        else:
            tip = tail.find("site[@name='tail_tip']") if tail is not None else None
            tip_pos = numbers(tip.get("pos"), 3) if tip is not None else None
            require("tail_tip_seam", v is not None and distance(v[3:], tip_pos) < 1e-7)
    require("tail_length_0p85m", abs(tail_length - 0.85) < 1e-5)

    head = bodies.get("head")
    horn_z = []
    for side in ("L", "R"):
        parts = ([head.find(f"geom[@name='horn_{side}_{i}']")
                  for i in range(3)] if head is not None else [None] * 3)
        lines = [numbers(p.get("fromto"), 6) if p is not None else None for p in parts]
        require("horn_rigid_geoms_on_head:" + side, all(p is not None for p in parts))
        for i in range(2):
            require(f"horn_seam:{side}:{i}->{i+1}", lines[i] is not None and
                    lines[i + 1] is not None and
                    distance(lines[i][3:], lines[i + 1][:3]) < 1e-7)
        tip = head.find(f"site[@name='horn_tip_{side}']") if head is not None else None
        tip_pos = numbers(tip.get("pos"), 3) if tip is not None else None
        require("horn_tip_seam:" + side, lines[2] is not None and
                distance(lines[2][3:], tip_pos) < 1e-7)
        require("no_horn_actuator:" + side,
                all("horn" not in str(j) for j in motor_joints))
        if tip_pos is not None and parts[2] is not None:
            radius = numbers(parts[2].get("size"), 1)
            if radius is not None:
                horn_z.append(tip_pos[2] + radius[0])
    crown = head.find("site[@name='crown']") if head is not None else None
    p = bodies.get("pelvis")
    t = bodies.get("torso")
    pos = [numbers(b.get("pos"), 3) if b is not None else None for b in (p, t, head)]
    crown_local = numbers(crown.get("pos"), 3) if crown is not None else None
    height_base = sum(v[2] for v in pos) if all(v is not None for v in pos) else math.nan
    crown_height = height_base + crown_local[2] if crown_local is not None else math.nan
    max_horn = height_base + max(horn_z) if len(horn_z) == 2 else math.nan
    require("neutral_crown_1p70m", abs(crown_height - 1.70) < 1e-5)
    require("neutral_horn_bound_1p92m", abs(max_horn - 1.92) < 1e-5)

    return {
        "pass": not failures,
        "failures": failures,
        "checks": checks,
        "metrics": {
            "body_count": len(bodies),
            "actuated_joints": len(named_joints),
            "motor_count": len(motors),
            "geometry_mass_kg": round(total_mass, 9),
            "tail_segments": len([n for n in bodies if n.startswith("tail_")]),
            "tail_centerline_m": round(tail_length, 9),
            "neutral_crown_m": round(crown_height, 9),
            "neutral_horn_bound_m": round(max_horn, 9),
        },
    }


def audit_native(path):
    """Compiled kinematic smoke checks: NOT a balance/gait disturbance test."""
    import mujoco
    import numpy as np

    model = mujoco.MjModel.from_xml_path(str(path))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    failures = []
    if model.nu != 55 or model.nv != 61 or not np.all(model.body_inertia[1:] > 0):
        failures.append("compiled_dofs_or_inertias")
    if abs(float(model.body_mass.sum()) - 78.) > 1e-5:
        failures.append("compiled_mass")
    reference_qpos = data.qpos.copy()

    def site(name):
        i = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, name)
        if i < 0:
            raise ValueError("missing site " + name)
        return data.site_xpos[i].copy()

    def geom(name):
        i = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, name)
        if i < 0:
            raise ValueError("missing geom " + name)
        return data.geom_xpos[i].copy()

    probes = [
        ("tail_yaw_1", lambda: site("tail_tip"), 1e-3),
        ("hip_pitch_L", lambda: site("foot_contact_L"), 1e-3),
        ("hip_pitch_R", lambda: site("foot_contact_R"), 1e-3),
        ("toe_flex_L_1", lambda: geom("toe_pad_L_1"), 1e-3),
        ("toe_flex_R_1", lambda: geom("toe_pad_R_1"), 1e-3),
    ]
    displacements = {}
    for joint_name, measure, threshold in probes:
        data.qpos[:] = reference_qpos
        mujoco.mj_forward(model, data)
        a = measure()
        j = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint_name)
        if j < 0:
            failures.append("native_missing_joint:" + joint_name)
            continue
        data.qpos[model.jnt_qposadr[j]] += 0.08
        mujoco.mj_forward(model, data)
        shift = float(np.linalg.norm(measure() - a))
        displacements[joint_name] = shift
        if not np.isfinite(shift) or shift <= threshold:
            failures.append("native_kinematic_no_response:" + joint_name)
    return {
        "pass": not failures, "failures": failures,
        "metrics": {"mujoco_version": mujoco.__version__, "native_body_count": model.nbody,
                    "native_nu": model.nu, "native_nv": model.nv,
                    "joint_probe_displacement_m": displacements},
    }


def audit_path(path, native=False):
    path = Path(path)
    try:
        result = audit_tree(ET.parse(path).getroot())
        result["source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        result["source"] = str(path)
        if native:
            result["native"] = audit_native(path)
            result["pass"] = result["pass"] and result["native"]["pass"]
    except Exception as error:
        result = {"pass": False, "failures": ["audit_execution:" +
                  type(error).__name__ + ":" + str(error)]}
    result["scope"] = "read_only_v03_rigid_proxy; never a live deployment"
    result["not_validated"] = [
        "18-vertebra anatomical tail (model has four rigid links)",
        "skin, musculature, ligaments, nerve/tissue clearance",
        "horn attachment strength/material behavior",
        "long-duration locomotion, running, external disturbance recovery",
        "physiological runtime integration and physical hardware",
    ]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--native", action="store_true",
                        help="Require an installed MuJoCo and run actual compilation/probes.")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = audit_path(args.model, native=args.native)
    serialized = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(serialized, encoding="utf-8")
    print(serialized)
    raise SystemExit(0 if receipt["pass"] else 1)


if __name__ == "__main__":
    main()
