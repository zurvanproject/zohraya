"""Read-only, reduced-order pelvic geometry and load fixture for Tadash.

This is a synthetic engineering model, not anatomy validated against a living
organism, pelvic-floor physiology, subjective sensation, or an actuator.
Coordinates: +X left, +Y forward, +Z up; all distances in metres.
"""
from dataclasses import dataclass
from math import cos, isfinite, sin, sqrt

SCHEMA = "tadash-pelvis/0.1"
SCOPE = "synthetic_readonly_geometry_and_load"


@dataclass(frozen=True)
class PelvisFixture:
    profile: str
    stature_m: float
    mass_kg: float
    hip_height_m: float
    hip_half_width_m: float
    pelvic_depth_m: float
    floor_area_m2: float
    floor_stiffness_n_m: float
    active_capacity_n: float
    max_deflection_m: float
    tail_length_m: float


# The 250-cm fixture matches the current repository phenotype/contact design.
# The separate portrait fixture reflects the 170-cm / 78-kg design discussion;
# its pelvic dimensions are explicitly *scaled guesses*, not measured anatomy.
_SCALE = 1.70 / 2.50
FIXTURES = {
    "runtime_250_195": PelvisFixture(
        "runtime_250_195", 2.50, 195., 1.42, .14, .25,
        .010, 5000., 75., .018, 1.20),
    "portrait_170_78": PelvisFixture(
        "portrait_170_78", 1.70, 78., 1.42 * _SCALE,
        .14 * _SCALE, .25 * _SCALE, .010 * _SCALE**2,
        5000. * _SCALE, 75. * _SCALE**2, .018 * _SCALE, .85),
}


def _number(value, name, low, high):
    if type(value) not in (float, int) or not isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name}: finite number in [{low}, {high}] required")
    return float(value)


def _rotate(point, *, pitch, roll, yaw):
    """Pitch about +X, roll about +Y, yaw about +Z, in that order."""
    x, y, z = point
    y, z = y * cos(pitch) - z * sin(pitch), y * sin(pitch) + z * cos(pitch)
    x, z = x * cos(roll) + z * sin(roll), -x * sin(roll) + z * cos(roll)
    return (x * cos(yaw) - y * sin(yaw), x * sin(yaw) + y * cos(yaw), z)


def evaluate_pelvis(*, profile="runtime_250_195", pitch_rad=0., roll_rad=0.,
                    yaw_rad=0., intra_abdominal_pressure_kpa=2.,
                    floor_activation=0., com_left_m=0., com_forward_m=0.):
    """Pure deterministic evaluation. Nothing advances the native Tadash body.

    Downward pressure load F = IAP * effective area. The passive pelvic-floor
    spring and active term are *invented* test coefficients. The rest of body
    weight is NOT carried by the pelvic floor. Saturation emits a guard.
    """
    if type(profile) is not str or profile not in FIXTURES:
        raise ValueError("unknown pelvic profile")
    d = FIXTURES[profile]
    pitch = _number(pitch_rad, "pitch", -.45, .45)
    roll = _number(roll_rad, "roll", -.45, .45)
    yaw = _number(yaw_rad, "yaw", -.70, .70)
    pressure = _number(intra_abdominal_pressure_kpa, "IAP", 0., 25.)
    activation = _number(floor_activation, "floor activation", 0., 1.)
    left = _number(com_left_m, "COM left shift", -.25, .25)
    forward = _number(com_forward_m, "COM forward shift", -.25, .25)

    scale = d.stature_m / 2.50
    local = {
        "hip_L": (d.hip_half_width_m, 0., 0.),
        "hip_R": (-d.hip_half_width_m, 0., 0.),
        "iliac_crest_L": (1.25 * d.hip_half_width_m, 0., .15 * scale),
        "iliac_crest_R": (-1.25 * d.hip_half_width_m, 0., .15 * scale),
        "pubic_symphysis": (0., d.pelvic_depth_m / 2., -.045 * scale),
        "sacrum_tail_root": (0., -d.pelvic_depth_m / 2., .05 * scale),
        "pelvic_floor_center": (0., 0., -.10 * scale),
    }
    landmarks = {
        name: [round(v + (d.hip_height_m if axis == 2 else 0.), 7)
               for axis, v in enumerate(_rotate(p, pitch=pitch, roll=roll, yaw=yaw))]
        for name, p in local.items()
    }
    hip_l, hip_r = landmarks["hip_L"], landmarks["hip_R"]
    hip_span = sqrt(sum((a - b)**2 for a, b in zip(hip_l, hip_r)))

    pressure_load_n = pressure * 1000. * d.floor_area_m2
    active_support_n = d.active_capacity_n * activation
    unconstrained_deflection = max(0., pressure_load_n - active_support_n) / d.floor_stiffness_n_m
    deflection = min(unconstrained_deflection, d.max_deflection_m)
    passive_support_n = d.floor_stiffness_n_m * deflection
    residual_n = max(0., pressure_load_n - active_support_n - passive_support_n)
    saturated = unconstrained_deflection > d.max_deflection_m + 1e-12
    weight_n = d.mass_kg * 9.81

    return {
        "schema": SCHEMA,
        "scope": SCOPE,
        "profile": d.profile,
        "geometry_source": "pelvic landmarks are synthetic; only runtime hip anchors are source-pinned",
        "mass_kg": d.mass_kg,
        "stature_m": d.stature_m,
        "axes": "+X left; +Y forward; +Z up",
        "landmarks_m": landmarks,
        "hip_span_m": round(hip_span, 7),
        "tail_length_m": d.tail_length_m,
        "floor_load_n": round(pressure_load_n, 6),
        "floor_active_support_n": round(active_support_n, 6),
        "floor_passive_support_n": round(passive_support_n, 6),
        "floor_residual_load_n": round(residual_n, 6),
        "floor_deflection_m": round(deflection, 7),
        "floor_saturated": saturated,
        "weight_n": round(weight_n, 4),
        "hip_roll_moment_nm": round(weight_n * left, 4),
        "hip_pitch_moment_nm": round(weight_n * forward, 4),
        "guard": "needs_review" if saturated else "within_synthetic_fixture",
        "native_cycles_caused": 0,
        "actuation_authorized": False,
        "subjective_or_sexual_response_inferred": False,
    }
