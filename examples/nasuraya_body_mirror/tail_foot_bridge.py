"""A reversible, read-only integration of Nasuraya motion v0.1 with native Tadash replay.

NEW 170cm/78kg/85cm character: reduced-order analytical physics only.
OLD source-pinned 250cm/195kg/120cm Tadash: inspected as recorded evidence
only. The two designs are NEVER silently mixed or used as one physical rig.

No native model write, actuator, internet, API, secrets or persistent agent.
The tail-foot controller gives ADVICE, never controls actual native joints.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILE = Path(__file__).resolve().parent / "design_profiles/nasuraya_170_78_85_v01.json"
G = 9.81


def finite(value, name, lo=None, hi=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("invalid finite " + name)
    if lo is not None and value < lo:
        raise ValueError(name + " below allowed minimum")
    if hi is not None and value > hi:
        raise ValueError(name + " above allowed maximum")
    return float(value)


def load_profile(path=PROFILE):
    p = json.loads(Path(path).read_text(encoding="utf-8"))
    if p.get("schema") != "nasuraya-tail-foot-design-profile/1":
        raise ValueError("unsupported movement profile")
    c, geom, motion = (p[k] for k in ("character", "geometry", "motion"))
    if (c.get("digitigrade") is not True or c.get("toes_per_foot") != 3 or
            c.get("fingers_per_hand") != 5 or c.get("horns") != 2):
        raise ValueError("Nasuraya phenotype contract was altered")
    finite(c["height_m"], "height", 1, 3)
    finite(c["mass_kg"], "mass", 30, 250)
    finite(c["tail_length_m"], "tail length", 0.2, 2)
    finite(c["tail_mass_assumed_kg"], "tail mass", .1, c["mass_kg"] / 4)
    finite(geom["foot_support_width_m"], "support width", .05, .40)
    finite(geom["body_com_height_assumed_m"], "COM height", .1, 2)
    finite(geom["tail_lateral_sweep_limit_deg"], "lateral sweep", 0, 80)
    for v in geom["stance_com_projection_m"]:
        finite(v, "COM projection", -.5, .5)
    for xy in [geom["ball_contact_center_m"], *geom["toe_contact_centers_m"]]:
        if not isinstance(xy, list) or len(xy) != 2:
            raise ValueError("foot contact vertices must be 2D")
        for v in xy:
            finite(v, "contact coordinate", -.5, .5)
    if len(geom["toe_contact_centers_m"]) != 3:
        raise ValueError("three toe contacts required")
    if abs(geom["toe_contact_centers_m"][-1][0] -
           geom["toe_contact_centers_m"][0][0] -
           geom["foot_support_width_m"]) > 1e-9:
        raise ValueError("toe geometry and declared support width disagree")
    for key in ("body_pitch_inertia_assumed_kg_m2", "disturbance_pitch_impulse_N_m_s",
                "tail_relative_sweep_rad", "tail_sweep_time_s",
                "tail_root_torque_limit_assumed_Nm", "tail_speed_limit_assumed_rad_s",
                "landing_drop_m", "human_equivalent_stiffness_N_m",
                "digitigrade_equivalent_stiffness_assumed_N_m"):
        finite(motion[key], key, 1e-6)
    finite(motion["gravitational_acceleration_m_s2"], "gravity", 9, 11)
    base = p["human_same_mass_comparator"]
    if base["mass_kg"] != c["mass_kg"]:
        raise ValueError("human baseline must match character body mass")
    for key in ("one_foot_effective_width_m", "body_com_height_assumed_m"):
        finite(base[key], key, .05, 3)
    for seq in p["sensitivity"].values():
        if not isinstance(seq, list) or not seq:
            raise ValueError("sensitivity groups cannot be empty")
        for value in seq:
            finite(value, "sensitivity parameter", 0)
    native = p["native_source_contract"]
    if (native["old_reference_height_m"] == c["height_m"] or
            native["old_reference_mass_kg"] == c["mass_kg"] or
            native["old_reference_tail_length_m"] == c["tail_length_m"]):
        raise ValueError("old and new geometry must remain separate")
    return p


def _sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observe_legacy_native(p, *, mirror_path=None):
    """Verify existing V06 record and report it without pretending it is 170/78."""
    contract = p["native_source_contract"]
    old = json.loads((ROOT / contract["contact_design_path"]).read_text())
    frames_path = (ROOT / contract["mirror_frames_path"] if mirror_path is None
                   else Path(mirror_path))
    mirror = json.loads(frames_path.read_text())
    phenotype = json.loads((ROOT / contract["phenotype_path"]).read_text())
    adult = phenotype["adult_scale"]
    if (old["schema"] != "tadash-contact-design/0.6" or
            old["mass_kg"] != contract["old_reference_mass_kg"] or
            old["tail_length_m"] != contract["old_reference_tail_length_m"] or
            adult["ground_to_crown_cm"] != round(100 * contract["old_reference_height_m"]) or
            adult["mass_target_kg"] != old["mass_kg"]):
        raise ValueError("native design disagrees with frozen legacy description")
    if (mirror.get("schema") != "nasuraya-body-mirror/1" or
            mirror.get("design", {}).get("patches") != old["patches"] or
            mirror["design"]["tail_length_m"] != old["tail_length_m"] or
            set(mirror["scenarios"]) != {"normal", "sleep"}):
        raise ValueError("recorded native replay shape mismatch")
    if mirror["runtime_manifest_sha256"] != _sha_file(
            ROOT / "runtimes/tadash_body/PUBLIC_FILES_SHA256.json"):
        raise ValueError("native source manifest changed")
    if {item["id"] for item in old["patches"]} != {
            "ball", "toe_1", "toe_2", "toe_3"}:
        raise ValueError("native three-toe support changed")
    observed = {}
    for fixture in ("normal", "sleep"):
        rows = mirror["scenarios"][fixture]["frames"]
        if len(rows) != 12:
            raise ValueError("native mirror recording must have 12 frames per fixture")
        angles = []
        acts = Counter()
        for frame in rows:
            sha = frame["checkpoint_sha256"]
            if not isinstance(sha, str) or len(sha) != 64 or any(
                    char not in "0123456789abcdef" for char in sha):
                raise ValueError("invalid native checkpoint fingerprint")
            if frame["actual"] not in ("walk", "observe", "protect"):
                raise ValueError("unsupported native action")
            for xyz in frame["feet_m"].values():
                if len(xyz) != 3 or any(
                        type(v) not in (int, float) or not math.isfinite(v) for v in xyz):
                    raise ValueError("invalid native foot location")
            if len(frame["tail_angle_rad"]) != 2:
                raise ValueError("native tail-angle vector must be yaw/pitch")
            for value in frame["tail_angle_rad"]:
                finite(value, "recorded native tail angle", -10, 10)
                angles.append(value)
            if len(frame["com_m"]) != 2:
                raise ValueError("invalid native COM record")
            for value in frame["com_m"]:
                finite(value, "recorded COM", -10, 10)
            acts[frame["actual"]] += 1
        observed[fixture] = dict(frames=len(rows), native_actions=dict(acts),
                                 max_abs_recorded_tail_angle_rad=max(map(abs, angles)),
                                 underlying_legacy_design_mass_kg=old["mass_kg"])
    return {
        "status": "verified existing synthetic native mirror; NOT a motion run of the 170/78/85 design",
        "legacy_height_m": contract["old_reference_height_m"],
        "legacy_mass_kg": old["mass_kg"],
        "legacy_tail_length_m": old["tail_length_m"],
        "native_tail_inertia_proxy_kg_m2": old["tail_inertia_kg_m2"],
        "native_tail_torque_ceiling_Nm": old["tail_torque_limit_Nm"],
        "native_contact_patch_count": len(old["patches"]),
        "source_hashes": {
            "V06_contact_sha256": _sha_file(ROOT / contract["contact_design_path"]),
            "V06_replay_sha256": _sha_file(frames_path)
        },
        "scenarios": observed,
        "not_rescaled_to_new_body": True,
    }


def hull(points):
    """Monotone-chain convex support hull, CCW; point centres only."""
    coords = sorted(set(tuple(map(float, p)) for p in points))
    if len(coords) < 3:
        raise ValueError("at least three distinct contact points required")
    cross = lambda o, a, b: (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    lower, upper = [], []
    for p in coords:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(coords):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    result = lower[:-1] + upper[:-1]
    if len(result) < 3:
        raise ValueError("collinear foot contacts")
    return result


def signed_margin(polygon, xy):
    """Signed minimum edge distance, positive if inside convex polygon."""
    px, py = map(float, xy)
    distances = []
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        ex, ey = b[0] - a[0], b[1] - a[1]
        norm = math.hypot(ex, ey)
        if norm < 1e-12:
            raise ValueError("degenerate contact hull")
        distances.append((ex*(py-a[1]) - ey*(px-a[0]))/norm)
    return min(distances)


def tail_inertia(mass, length):
    return mass * length**2 / 3  # thin, rigid, uniform tail rod; assumption


def cosine_sweep(t, amplitude, seconds):
    s = min(max(t / seconds, 0), 1)
    return amplitude * (1 - math.cos(math.pi * s)) / 2


def pitch_trial(p, *, tail_mass=None, time_s=None):
    c, motion = p["character"], p["motion"]
    tm = c["tail_mass_assumed_kg"] if tail_mass is None else finite(
        tail_mass, "tail mass variation", .1, c["mass_kg"] / 4)
    time = motion["tail_sweep_time_s"] if time_s is None else finite(
        time_s, "time", 0, motion["tail_sweep_time_s"])
    I_body = motion["body_pitch_inertia_assumed_kg_m2"]
    I_tail = tail_inertia(tm, c["tail_length_m"])
    I_red = I_body * I_tail / (I_body + I_tail)
    requested = motion["tail_relative_sweep_rad"]
    T = motion["tail_sweep_time_s"]
    speed_required = requested * math.pi / (2 * T)
    torque_required = I_red * requested * math.pi**2 / (2 * T*T)
    speed_cap = motion["tail_speed_limit_assumed_rad_s"]
    torque_cap = motion["tail_root_torque_limit_assumed_Nm"]
    scale = min(1, speed_cap / speed_required, torque_cap / torque_required)
    sweep = requested * scale
    phi = cosine_sweep(time, sweep, T)
    J = motion["disturbance_pitch_impulse_N_m_s"]
    human = J * time / I_body
    passive = J * time / (I_body + I_tail)
    active = passive - I_tail * phi / (I_body + I_tail)
    return {
        "human_tailless_pitch_deg": math.degrees(human),
        "digitigrade_passive_tail_pitch_deg": math.degrees(passive),
        "digitigrade_active_tail_pitch_deg": math.degrees(active),
        "effective_tail_sweep_deg": math.degrees(sweep),
        "tail_sweep_limited_by_assumed_actuator": scale < 1 - 1e-12,
        "tail_peak_speed_rad_s": speed_required * scale,
        "tail_peak_root_torque_Nm": torque_required * scale,
        "tail_equivalent_inertia_kg_m2": I_tail,
        "inertia_model": "2 rigid rotors with angular impulse; no external aerodynamic forces",
    }


def footing_trial(p, *, com_x=None, com_y=None):
    c, geom, human = p["character"], p["geometry"], p["human_same_mass_comparator"]
    nominal_x, nominal_y = geom["stance_com_projection_m"]
    x = nominal_x if com_x is None else finite(com_x, "COM lateral projection", -.5, .5)
    y = nominal_y if com_y is None else finite(com_y, "COM forward projection", -.5, .5)
    poly = hull([geom["ball_contact_center_m"], *geom["toe_contact_centers_m"]])
    static = signed_margin(poly, [x, y])
    possible_shift = (c["tail_mass_assumed_kg"] * (c["tail_length_m"] / 2) *
        math.sin(math.radians(geom["tail_lateral_sweep_limit_deg"])) / c["mass_kg"])
    applied_shift = min(abs(x), possible_shift)
    assisted_x = x - math.copysign(applied_shift, x)
    improved = signed_margin(poly, [assisted_x, y])
    hm = human["one_foot_effective_width_m"] / 2 - abs(x)
    return {
        "foot_polygon_centres_xy_m": [list(point) for point in poly],
        "com_projection_m": [x, y],
        "digitigrade_signed_contact_centre_margin_m": static,
        "with_tail_lateral_shift_margin_m": improved,
        "human_rectangular_lateral_margin_m": hm,
        "tail_shift_applied_m": applied_shift,
        "required_tail_lateral_sweep_deg": math.degrees(
            math.asin(min(1.0, applied_shift * c["mass_kg"] /
                (c["tail_mass_assumed_kg"] * c["tail_length_m"] / 2)))),
        "static_contact_centre_hull_only": True,
        "toe_pad_areas_and_friction_not_calibrated_for_new_profile": True,
    }


def landing_trial(p, *, spring=None):
    motion=p["motion"]
    k = motion["digitigrade_equivalent_stiffness_assumed_N_m"] if spring is None else finite(
        spring, "landing stiffness", 1000)
    def landing(stiffness):
        mg = p["character"]["mass_kg"] * motion["gravitational_acceleration_m_s2"]
        h = motion["landing_drop_m"]
        x = (mg + math.sqrt(mg*mg + 2*stiffness*mg*h)) / stiffness
        return {"peak_spring_force_N": stiffness*x, "compression_m": x,
                "peak_force_bodyweights": stiffness*x/mg}
    b = landing(motion["human_equivalent_stiffness_N_m"])
    d = landing(k)
    return {"human": b, "digitigrade": d,
            "relative_peak_force_reduction_pct": 100*(1 - d["peak_spring_force_N"] /
                                                      b["peak_spring_force_N"]),
            "unvalidated_equivalent_linear_spring_only": True}


def coordination_advisory(p, *, com_xy=None):
    """A pure bounded tail+foot suggestion. NEVER writes to Tadash control."""
    foot = footing_trial(p, **({} if com_xy is None else {
        "com_x": com_xy[0], "com_y": com_xy[1]}))
    pitch = pitch_trial(p)
    margin = foot["with_tail_lateral_shift_margin_m"]
    action = "hold_and_reassess" if margin < 0 else (
        "reduce_step_and_recheck_contact" if margin < 0.012 else
        "optional_step_candidate")
    return {
        "mode": "advisory_only_no_actuation",
        "foot_action_recommendation": action,
        "predicted_tail_lateral_offset_m": foot["tail_shift_applied_m"],
        "suggested_tail_lateral_sweep_deg": foot["required_tail_lateral_sweep_deg"],
        "suggested_pitch_sweep_deg": pitch["effective_tail_sweep_deg"],
        "tail_root_torque_estimate_Nm": pitch["tail_peak_root_torque_Nm"],
        "native_action_authorized": False,
        "safety_veto_unchanged": True,
    }


def report(p=None, *, native_mirror=None):
    p = load_profile() if p is None else p
    main = pitch_trial(p)
    footing = footing_trial(p)
    landing = landing_trial(p)
    return {
        "schema": "nasuraya-tail-foot-motion-native-mirror-bridge/1",
        "new_profile": p["name"],
        "new_profile_height_m": p["character"]["height_m"],
        "new_profile_mass_kg": p["character"]["mass_kg"],
        "new_profile_tail_length_m": p["character"]["tail_length_m"],
        "analytical_pitch": main,
        "analytical_footing": footing,
        "analytical_landing": landing,
        "coordination_advice": coordination_advisory(p),
        "tail_mass_sensitivity": [
            dict(tail_mass_kg=m, **pitch_trial(p, tail_mass=m))
            for m in p["sensitivity"]["tail_mass_kg"]],
        "foot_offset_sensitivity": [
            dict(lateral_offset_m=x, **footing_trial(p, com_x=x))
            for x in p["sensitivity"]["foothold_lateral_offset_m"]],
        "friction_sensitivity": [
            {"mu_assumed":mu,
             "ideal_gravity_limited_lateral_acceleration_m_s2":
                 mu*p["motion"]["gravitational_acceleration_m_s2"]}
            for mu in p["sensitivity"]["friction_coefficients"]],
        "landing_sensitivity": [
            dict(stiffness_N_m=k, **landing_trial(p, spring=k))
            for k in p["sensitivity"]["landing_stiffness_N_m"]],
        "native_V06_replay_observed_separately": observe_legacy_native(p, mirror_path=native_mirror),
        "native_170cm_simulation_executed": False,
        "existing_native_controller_modified": False,
        "paid_api_calls": 0,
        "limits": p["limitations"],
    }


def save(directory, *, native_mirror=None):
    output=Path(directory)
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    p=load_profile()
    results=report(p, native_mirror=native_mirror)
    (output/"report.json").write_text(json.dumps(results, indent=2,
                        ensure_ascii=False, sort_keys=True, allow_nan=False)+"\n", encoding="utf-8")
    with (output/"tail_pitch.csv").open("x", newline="", encoding="utf-8") as f:
        writer=csv.writer(f)
        writer.writerow(["time_s","human_deg","tail_passive_deg","tail_active_deg"])
        T=p["motion"]["tail_sweep_time_s"]
        for j in range(101):
            t=T*j/100
            trial=pitch_trial(p,time_s=t)
            writer.writerow([round(t,6),trial["human_tailless_pitch_deg"],
                trial["digitigrade_passive_tail_pitch_deg"],
                trial["digitigrade_active_tail_pitch_deg"]])
    return results


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--native-mirror",type=Path,help="optional freshly exported V06 mirror recording; still NOT a 170cm run")
    args=parser.parse_args(argv)
    data=save(args.output_dir, native_mirror=args.native_mirror)
    print(json.dumps({
        "schema":data["schema"],
        "native_170cm_simulation_executed":False,
        "native_V06_frame_count":sum(
            x["frames"] for x in data["native_V06_replay_observed_separately"]["scenarios"].values()),
        "active_tail_final_pitch_deg":data["analytical_pitch"]["digitigrade_active_tail_pitch_deg"],
        "advice":data["coordination_advice"]["foot_action_recommendation"],
        "paid_api_calls":0
    },ensure_ascii=False,sort_keys=True))


if __name__ == "__main__":
    main()
