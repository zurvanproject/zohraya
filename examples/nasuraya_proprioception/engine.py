"""Conservative simulated proprioception advisory, not an actuator or physics engine.

Model profile is a provisional 170 cm / 78 kg concept. In particular, no
114-DOF rig, measured tail dynamics, real injury threshold, or physical sensor
is asserted. This module never modifies Tadash/UnifiedBody checkpoints.
"""
from dataclasses import dataclass, field
import math
from typing import Mapping

SCHEMA = "nasuraya-proprioception-advisory/0.1"
SOURCE = "SIMULATED_SYNTHETIC_PROPRIOCEPTION"
# Deliberately only joint commands for which a bounded interface is specified.
ROM = {
    "TAIL_PITCH": (-65.0, 95.0),
    "ANKLE_L": (15.0, 85.0),
    "ANKLE_R": (15.0, 85.0),
    "HIP_L": (-35.0, 130.0),
    "HIP_R": (-35.0, 130.0),
}
MAX_TORQUE_NM = {
    "TAIL_PITCH": 48.0, "ANKLE_L": 210.0, "ANKLE_R": 210.0,
    "HIP_L": 260.0, "HIP_R": 260.0,
}
ALLOWED_INTENTS = {"OBSERVE", "HOLD", "STEP"}
MAX_DELAY_MS = 100.0
MAX_DT_S = 0.1


def finite_number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name}: finite numeric value required")
    return float(value)


def vector(values, size, name):
    if not isinstance(values, (list, tuple)) or len(values) != size:
        raise ValueError(f"{name}: expected {size} values")
    return tuple(finite_number(v, name) for v in values)


def cross(a, b, c):
    return ((b[0] - a[0]) * (c[1] - a[1])
            - (b[1] - a[1]) * (c[0] - a[0]))


def convex_hull(points):
    """CCW convex hull of actual contacting toe points, not their bounding box."""
    p = sorted(set(vector(x, 2, "toe position") for x in points))
    if len(p) < 3:
        return ()
    lower = []
    for q in p:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    upper = []
    for q in reversed(p):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    hull = tuple(lower[:-1] + upper[:-1])
    return hull if len(hull) >= 3 and abs(cross(*hull[:3])) > 1e-12 else ()


def signed_margin(point, polygon):
    """Minimum signed perpendicular distance to every CCW support edge."""
    if len(polygon) < 3:
        return None
    p = vector(point, 2, "xcom")
    distances = []
    for i, a in enumerate(polygon):
        b = polygon[(i + 1) % len(polygon)]
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length <= 1e-12:
            return None
        distances.append(cross(a, b, p) / length)
    return round(min(distances), 6)


@dataclass(frozen=True)
class Foot:
    """Three toes in a fixed world frame: x forward, y left, z upward."""
    toe_positions_xy_m: tuple
    toe_contact: tuple
    normal_force_n: float
    tangential_force_xy_n: tuple
    friction_mu: float

    def validate(self):
        if not isinstance(self.toe_positions_xy_m, (tuple, list)) or len(self.toe_positions_xy_m) != 3:
            raise ValueError("exactly three toe positions required")
        if not isinstance(self.toe_contact, (tuple, list)) or len(self.toe_contact) != 3:
            raise ValueError("exactly three toe contact flags required")
        if any(type(x) is not bool for x in self.toe_contact):
            raise ValueError("toe contact flags must be bool")
        for p in self.toe_positions_xy_m:
            vector(p, 2, "toe position")
        vector(self.tangential_force_xy_n, 2, "tangential force")
        normal = finite_number(self.normal_force_n, "normal force")
        mu = finite_number(self.friction_mu, "friction")
        if normal < 0 or not 0 <= mu <= 2:
            raise ValueError("invalid normal force or friction")
        if not any(self.toe_contact) and abs(normal) > 1e-12:
            raise ValueError("airborne foot cannot declare nonzero normal force")

    def contact_points(self):
        return [tuple(p) for p, yes in zip(self.toe_positions_xy_m, self.toe_contact)
                if yes and self.normal_force_n > 0]

    def slip_utilization(self):
        if not any(self.toe_contact):
            return 0.0
        tangential = math.hypot(*self.tangential_force_xy_n)
        denominator = self.friction_mu * self.normal_force_n
        if denominator <= 0:
            return None  # Treat as impossible/unsafe, not a fake finite value.
        return tangential / denominator


@dataclass(frozen=True)
class Packet:
    timestamp_ms: float
    dt_s: float
    source_type: str
    com_xyz_m: tuple
    velocity_xyz_m_s: tuple
    gravity_xyz_m_s2: tuple
    left: Foot
    right: Foot
    sensor_delay_ms: float = 0.0
    noise_std_m: float = 0.0
    # No unvalidated floating command can be forwarded as a physical actuator.
    joint_angles_deg: Mapping[str, float] = field(default_factory=dict)

    def validate(self):
        if self.source_type != SOURCE:
            raise ValueError("only explicitly identified synthetic inputs allowed")
        if finite_number(self.timestamp_ms, "timestamp") < 0:
            raise ValueError("negative timestamp")
        dt = finite_number(self.dt_s, "dt")
        if not 0 < dt <= MAX_DT_S:
            raise ValueError("sample interval out of range")
        vector(self.com_xyz_m, 3, "center of mass")
        vector(self.velocity_xyz_m_s, 3, "velocity")
        g = vector(self.gravity_xyz_m_s2, 3, "gravity")
        if not 1 <= math.sqrt(sum(x*x for x in g)) <= 25:
            raise ValueError("gravity magnitude outside model domain")
        if self.com_xyz_m[2] <= 0:
            raise ValueError("center-of-mass height must be positive")
        delay = finite_number(self.sensor_delay_ms, "sensor delay")
        noise = finite_number(self.noise_std_m, "noise")
        if delay < 0 or noise < 0:
            raise ValueError("negative sensor delay/noise")
        for joint, angle in self.joint_angles_deg.items():
            if joint not in ROM:
                raise ValueError("unknown joint angle: " + str(joint))
            finite_number(angle, "joint angle")
        self.left.validate()
        self.right.validate()


def assess(packet: Packet, *, intent: str = "OBSERVE",
           requested_torques_nm: Mapping[str, float] | None = None) -> dict:
    """Fail-closed advisory. Never sends actuation or changes canonical state."""
    packet.validate()
    if intent not in ALLOWED_INTENTS:
        raise ValueError("unknown intent")
    torques = dict(requested_torques_nm or {})
    for name, value in torques.items():
        if name not in MAX_TORQUE_NM:
            raise ValueError("unknown requested torque joint: " + str(name))
        finite_number(value, "requested torque")
    g = packet.gravity_xyz_m_s2
    near_vertical = abs(g[0]) <= 1e-8 and abs(g[1]) <= 1e-8 and g[2] < 0
    # Orthogonal-ground XCoM formula has not been calibrated for tilted fields.
    omega = (math.sqrt(-g[2] / packet.com_xyz_m[2]) if near_vertical else None)
    delay_s = packet.sensor_delay_ms / 1000.0
    estimated_xy = tuple(packet.com_xyz_m[k] + packet.velocity_xyz_m_s[k] * delay_s
                         for k in (0, 1))
    xcom_xy = (tuple(estimated_xy[k] + packet.velocity_xyz_m_s[k] / omega
                     for k in (0, 1)) if omega else None)

    points = packet.left.contact_points() + packet.right.contact_points()
    hull = convex_hull(points)
    margin = signed_margin(xcom_xy, hull) if xcom_xy is not None else None
    slip = [f.slip_utilization() for f in (packet.left, packet.right)
            if any(f.toe_contact)]
    slip_problem = any(v is None for v in slip)
    max_slip = max((v for v in slip if v is not None), default=0.0)
    torque_ratio = max((abs(value) / MAX_TORQUE_NM[j] for j, value in torques.items()),
                       default=0.0)
    angles_valid = all(ROM[j][0] <= a <= ROM[j][1]
                       for j, a in packet.joint_angles_deg.items())
    reasons = []
    if not near_vertical:
        reasons.append("UNSUPPORTED_TILTED_GRAVITY")
    if not hull:
        reasons.append("NO_VALID_SUPPORT_POLYGON")
    if packet.sensor_delay_ms > MAX_DELAY_MS:
        reasons.append("STALE_SENSOR")
    if slip_problem or max_slip >= 1.0:
        reasons.append("FRICTION_CONE_VIOLATION")
    if torque_ratio > 1.0:
        reasons.append("JOINT_TORQUE_LIMIT")
    if not angles_valid:
        reasons.append("JOINT_ROM_LIMIT")
    if margin is not None and margin < 0:
        reasons.append("XCOM_OUTSIDE_SUPPORT")
    # Bounded heuristic, explicitly not a calibrated fall probability.
    margin_penalty = (1.0 if margin is None else
                      min(1.0, max(0.0, 1.0 - margin / 0.045)))
    sensor_penalty = min(1.0, delay_s / 0.1 + packet.noise_std_m / 0.01)
    eui = min(1.0, (0.4 * margin_penalty + 0.25 * min(1.0, torque_ratio)
                    + 0.2 * min(1.0, max_slip if not slip_problem else 1.0)
                    + 0.15 * sensor_penalty))
    if not reasons and eui >= 0.65:
        reasons.append("HIGH_UNCALIBRATED_INSTABILITY_INDEX")
    permitted = not reasons and intent in {"OBSERVE", "HOLD"}
    # STEP is deliberately not authorized by an engineering toy estimator.
    if intent == "STEP":
        reasons.append("NO_AUTHORIZED_MOTOR_ACTUATOR")
    return {
        "schema": SCHEMA,
        "source_type": SOURCE,
        "timestamp_ms": packet.timestamp_ms,
        "intent": intent,
        "xcom_xy_m": (tuple(round(x, 6) for x in xcom_xy)
                       if xcom_xy is not None else None),
        "support_polygon_xy_m": [list(p) for p in hull],
        "signed_margin_m": margin,
        "slip_ratio_max": round(max_slip, 6) if not slip_problem else None,
        "eui": round(eui, 6),
        "eui_is": "uncalibrated_engineering_index_not_probability",
        "action_advisory": ("OBSERVE_ONLY" if permitted else "DENY_MOTION"),
        "reasons": reasons,
        "motion_execution": False,
        "real_sensor_validation": False,
        "canonical_checkpoint_modified": False,
    }
