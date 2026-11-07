"""Synthetic 3-D pelvic tail/pudendal corridor and uterovaginal strain sidecar.

All coordinates and radii are engineered hypotheses, not measured anatomy,
finite-element mechanics, anatomical clearance certification or sensation.
Read-only: does not step Tadash, change checkpoint, command an actuator, or
model biological sexual/reproductive function.
"""
from math import isfinite, sqrt

from .pelvis_v01 import FIXTURES, evaluate_pelvis
from .pelvis_observer_v02 import observe_pelvis
from .pelvic_neurovisceral_v03 import assess_neurovisceral_pelvis

SCHEMA = "tadash-pelvic-clearance/0.4"


def _dot(u, v):
    return sum(a * b for a, b in zip(u, v))


def _sub(u, v):
    return [a - b for a, b in zip(u, v)]


def _clip(x):
    return min(1.0, max(0.0, x))


def segment_distance_m(p1, q1, p2, q2):
    """Exact distance between two finite 3-D line segments, including zero length."""
    points = (p1, q1, p2, q2)
    if any(not isinstance(p, (list, tuple)) or len(p) != 3 or
           any(type(v) not in (int, float) or not isfinite(v) for v in p)
           for p in points):
        raise ValueError("finite three-dimensional segment points required")
    u = _sub(q1, p1)
    v = _sub(q2, p2)
    w = _sub(p1, p2)
    a, e = _dot(u, u), _dot(v, v)
    eps = 1e-18
    if a <= eps and e <= eps:
        return sqrt(_dot(w, w))
    if a <= eps:
        s, t = 0., _clip(_dot(v, w) / e)
    else:
        c = _dot(u, w)
        if e <= eps:
            s, t = _clip(-c / a), 0.
        else:
            b, f = _dot(u, v), _dot(v, w)
            denom = a * e - b * b
            s = _clip((b * f - c * e) / denom) if denom > eps else 0.
            t = (b * s + f) / e
            if t < 0.:
                s, t = _clip(-c / a), 0.
            elif t > 1.:
                s, t = _clip((b - c) / a), 1.
    closest = [w[i] + s * u[i] - t * v[i] for i in range(3)]
    return sqrt(_dot(closest, closest))


def _finite_offset(value):
    if type(value) not in (int, float) or not isfinite(value) or not -1 <= value <= 1:
        raise ValueError("tail_socket_lateral_fraction must be finite in [-1, 1]")
    return float(value)


def evaluate_pelvic_clearance(*, profile="portrait_170_78",
                              posture_snapshot=None,
                              tail_socket_lateral_fraction=0.,
                              intra_abdominal_pressure_kpa=2.,
                              floor_activation=.3,
                              vaginal_wall_load=.2,
                              uterine_activity=.2):
    """Pure inspection of a fabricated geometry over existing v0.1-v0.3 models.

    tail_socket_lateral_fraction is an *adversarial placement test*; the model
    never alters a body tail. Native V06 snapshots are not rescaled to portrait.
    """
    fraction = _finite_offset(tail_socket_lateral_fraction)
    nerve = assess_neurovisceral_pelvis(
        profile=profile, posture_snapshot=posture_snapshot,
        intra_abdominal_pressure_kpa=intra_abdominal_pressure_kpa,
        floor_activation=floor_activation, vaginal_wall_load=vaginal_wall_load,
        uterine_activity=uterine_activity)
    fixture = FIXTURES[profile]
    s = fixture.stature_m / 2.5
    if posture_snapshot is None:
        base = evaluate_pelvis(profile=profile,
                  intra_abdominal_pressure_kpa=intra_abdominal_pressure_kpa,
                  floor_activation=floor_activation)
        landmarks = base["landmarks_m"]
        source = "synthetic_fixture"
    else:
        overlay = observe_pelvis(posture_snapshot, profile=profile,
                  intra_abdominal_pressure_kpa=intra_abdominal_pressure_kpa,
                  floor_activation=floor_activation)
        landmarks = overlay["pelvis_landmarks_world_m"]
        source = "caller_declared_V06_snapshot_not_cryptographically_verified"
    tail = landmarks["sacrum_tail_root"]
    floor = landmarks["pelvic_floor_center"]
    shift = fraction * .12 * s
    tail_path = [
        [tail[0] + shift, tail[1], tail[2]],
        [tail[0] + shift, tail[1] - .07 * s, tail[2] - .04 * s],
    ]
    corridors = {}
    clearances = {}
    for side, direction in (("L", 1), ("R", -1)):
        # Only illustrative centers ordered like the real nerve route:
        # S2-S4 -> greater foramen -> ischial spine -> lesser foramen ->
        # Alcock canal -> perineal endpoint. Not anatomical coordinates.
        offsets = [
            (.067, -.045, -.015),
            (.093, -.105, -.045),
            (.115, -.075, -.075),
            (.111, -.045, -.105),
            (.100,  .005, -.130),
            (.062,  .055, -.140),
        ]
        points = [[round(tail[0] + direction * x * s, 8),
                   round(tail[1] + (y + .125) * s, 8),
                   round(tail[2] + z * s, 8)] for x, y, z in offsets]
        centerline = min(segment_distance_m(tail_path[0], tail_path[1],
                        points[i], points[i+1]) for i in range(len(points)-1))
        # Combined hypothetical tube radii. Equal on both sides.
        clearance = centerline - (.044 + .008) * s
        corridors[side] = {
            "sequence": ["S2_S4", "greater_sciatic_foramen",
                         "ischial_spine", "lesser_sciatic_foramen",
                         "Alcock_canal", "perineal_endpoint"],
            "centerline_m": points,
            "minimum_centerline_distance_m": round(centerline, 7),
            "hypothetical_tube_clearance_mm": round(1000 * clearance, 4),
        }
        clearances[side] = clearance

    vaginal_wall_fraction = nerve["viscera"]["vaginal_wall_load_proxy"]
    uterine_activity_fraction = nerve["viscera"]["uterine_activity_proxy"]
    max_floor = fixture.max_deflection_m
    floor_ratio = nerve["pelvic_floor"]["deflection_m"] / max_floor
    # Deliberately different compartments; not a constitutive tissue law.
    vaginal_radial_shift_m = s * (.009 * vaginal_wall_fraction + .001 * floor_ratio)
    uterine_axial_shift_m = s * (.008 * uterine_activity_fraction + .0005 * floor_ratio)
    organs = {
        "bladder": {
            "center_m": [round(floor[0], 7), round(floor[1] + .09*s, 7), round(floor[2] + .085*s, 7)],
            "semiaxes_m": [round(.048*s, 7),round(.045*s, 7),round(.042*s, 7)],
            "role": "anterior_urinary",
        },
        "vagina": {
            "center_m": [round(floor[0], 7), round(floor[1] + .015*s, 7), round(floor[2] + .055*s, 7)],
            "radial_displacement_proxy_mm": round(1000*vaginal_radial_shift_m, 4),
            "semiaxes_m": [round(.028*s + vaginal_radial_shift_m, 7), round(.025*s + vaginal_radial_shift_m, 7), round(.071*s, 7)],
            "role": "middle_genital_canal",
        },
        "uterus": {
            "center_m": [round(floor[0], 7), round(floor[1] - .015*s, 7), round(floor[2] + .14*s, 7)],
            "axial_displacement_proxy_mm": round(1000*uterine_axial_shift_m, 4),
            "semiaxes_m": [round(.043*s, 7), round(.035*s, 7), round(.040*s + uterine_axial_shift_m, 7)],
            "role": "superior_to_vaginal_canal",
        },
        "rectum": {
            "center_m": [round(floor[0], 7), round(floor[1] - .085*s, 7), round(floor[2] + .085*s, 7)],
            "semiaxes_m": [round(.030*s, 7), round(.045*s, 7), round(.050*s, 7)],
            "role": "posterior_bowel",
        },
    }
    causes = list(nerve["guard_reasons"])
    if min(clearances.values()) <= 0.:
        causes.append("hypothetical_tail_nerve_corridor_overlap")
    elif min(clearances.values()) < .007 * s:
        causes.append("hypothetical_corridor_narrow_margin")
    if vaginal_radial_shift_m > .0075 * s:
        causes.append("synthetic_vaginal_wall_shift_limit")
    if uterine_axial_shift_m > .0065 * s:
        causes.append("synthetic_uterine_displacement_limit")
    return {
        "schema": SCHEMA,
        "scope": "fabricated_geometry_and_uncalibrated_mechanics_readonly",
        "profile": profile,
        "source": source,
        "landmarks_m": {"sacrum_tail_root": list(tail),
                        "pelvic_floor_center": list(floor)},
        "tail_root_sleeve_segment_m": tail_path,
        "tail_root_radius_assumption_mm": round(44*s, 4),
        "nerve_tube_radius_assumption_mm": round(8*s, 4),
        "pudendal_routes": corridors,
        "minimum_hypothetical_clearance_mm": round(1000 * min(clearances.values()), 4),
        "visceral_compartments": organs,
        "guard": "review_required" if causes else "within_synthetic_fixture",
        "guard_reasons": causes,
        "anatomy_validated": False,
        "biological_clearance_or_tissue_safety_established": False,
        "vasculature_explicitly_mesh_modeled": False,
        "full_tail_routing_simulated": False,
        "clinical_validity": False,
        "native_cycles_caused": 0,
        "actuation_authorized": False,
        "sexual_state_inferred": False,
        "subjective_sensation_inferred": False,
        "reproductive_function_verified": False,
    }
