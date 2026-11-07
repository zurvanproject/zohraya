"""Offline synthetic motion inspection: paired nerve, artery, vein and tail root.
All coordinates and radii are invented engineering proxies; no biological
validation, physiological actuation, subjective experience or live state change.
"""
from math import isfinite, sin, cos, pi
from .pelvic_clearance_v04 import evaluate_pelvic_clearance, segment_distance_m
from .pelvis_v01 import FIXTURES

SCHEMA = "tadash-pelvic-motion/0.5"
MAX_FRAMES = 601


def _real(x, name, low, high):
    if type(x) not in (float, int) or not isfinite(x) or not low <= x <= high:
        raise ValueError(f"{name} must be finite in [{low}, {high}]")
    return float(x)


def generate_synthetic_tail_sweep(*, duration_s=2., step_s=.02,
                                  amplitude_rad=1.8, frequency_hz=.5):
    """Generate fixed-root proximal tail rotation; NOT a measured dance."""
    duration = _real(duration_s, "duration", .02, 15.)
    dt = _real(step_s, "step", .01, .5)
    amp = _real(amplitude_rad, "amplitude_rad", 0, 2.2)
    hz = _real(frequency_hz, "frequency", 0, 3.)
    n = round(duration / dt)
    if not 1 <= n <= MAX_FRAMES - 1 or abs(n * dt - duration) > 1e-8:
        raise ValueError("duration must exactly fit step and frame limit")
    return [{"t_s": round(i * dt, 8),
             "tail_base_yaw_rad": round(amp * sin(2*pi*hz*i*dt), 10)}
            for i in range(n + 1)]


def _validate_frames(frames):
    if type(frames) not in (tuple, list) or not 2 <= len(frames) <= MAX_FRAMES:
        raise ValueError("2..601 frames required")
    clean = []
    previous = -1.
    for frame in frames:
        if type(frame) is not dict or set(frame) != {"t_s", "tail_base_yaw_rad"}:
            raise ValueError("exactly t_s and tail_base_yaw_rad required")
        t = _real(frame["t_s"], "time", 0., 15.)
        yaw = _real(frame["tail_base_yaw_rad"], "yaw", -2.2, 2.2)
        if t <= previous:
            raise ValueError("frame times must increase strictly")
        clean.append((t, yaw))
        previous = t
    return clean


def _tube_margin_mm(tail, points, radius_sum_m, scale):
    center = min(segment_distance_m(tail[0], tail[1], points[i], points[i+1])
                 for i in range(len(points) - 1))
    return round(1000 * (center - radius_sum_m * scale), 4)


def _vessel_margin_mm(tail, nerve_points, side, kind, scale):
    # Fictional vascular offsets from the ordinal pudendal landmarks.
    # These are NOT a vascular atlas or clinical caliber estimates.
    sign = 1 if side == "L" else -1
    if kind == "internal_pudendal_artery":
        lateral, anterior, radius = .010, .003, .005
    elif kind == "internal_pudendal_vein":
        lateral, anterior, radius = .015, -.003, .0045
    else:
        raise ValueError("unknown vessel")
    points = [[p[0]+sign*lateral*scale, p[1]+anterior*scale, p[2]]
              for p in nerve_points]
    return _tube_margin_mm(tail, points, .044 + radius, scale)


def evaluate_tail_neurovascular_motion(*, profile="portrait_170_78",
                                       motion_frames=None,
                                       intra_abdominal_pressure_kpa=2.,
                                       floor_activation=.3):
    """Read-only synthetic motion clearance; positive margin != biological safety."""
    if type(profile) is not str or profile not in FIXTURES:
        raise ValueError("unknown profile")
    if motion_frames is None:
        motion_frames = generate_synthetic_tail_sweep()
        origin = "generated_hypothetical_samples"
    else:
        origin = "caller_supplied_unverified_samples"
    frames = _validate_frames(motion_frames)
    scale = FIXTURES[profile].stature_m / 2.5
    kinds = ("pudendal_nerve", "internal_pudendal_artery", "internal_pudendal_vein")
    worst = {side: {kind: (float("inf"), None) for kind in kinds}
             for side in ("L", "R")}
    series, first_alert, alert_count, fixed_anchor = [], None, 0, None
    for t, yaw in frames:
        static = evaluate_pelvic_clearance(
            profile=profile, tail_socket_lateral_fraction=0.,
            intra_abdominal_pressure_kpa=intra_abdominal_pressure_kpa,
            floor_activation=floor_activation)
        anchor = static["landmarks_m"]["sacrum_tail_root"]
        if fixed_anchor is None:
            fixed_anchor = list(anchor)
        elif anchor != fixed_anchor:
            raise RuntimeError("fixed sacral attachment unexpectedly changed")
        # Root stays fixed. Only the hypothetical proximal tail segment rotates.
        tail = [list(anchor),
                [anchor[0]+.18*scale*sin(yaw),
                 anchor[1]-.18*scale*cos(yaw), anchor[2]-.04*scale]]
        reasons = set(static["guard_reasons"])
        minimum = float("inf")
        for side in ("L", "R"):
            points = static["pudendal_routes"][side]["centerline_m"]
            margins = {
                "pudendal_nerve": _tube_margin_mm(tail, points, .044+.008, scale),
                "internal_pudendal_artery": _vessel_margin_mm(
                    tail, points, side, "internal_pudendal_artery", scale),
                "internal_pudendal_vein": _vessel_margin_mm(
                    tail, points, side, "internal_pudendal_vein", scale),
            }
            for kind, margin in margins.items():
                if margin < worst[side][kind][0]:
                    worst[side][kind] = (margin, t)
                minimum = min(minimum, margin)
                if margin <= 0:
                    reasons.add("hypothetical_" + kind + "_tube_overlap_" + side)
                elif margin < 7*scale:
                    reasons.add("hypothetical_" + kind + "_narrow_margin_" + side)
        if reasons:
            alert_count += 1
            if first_alert is None:
                first_alert = t
        series.append({
            "t_s": round(t, 8),
            "tail_base_yaw_rad": round(yaw, 10),
            "min_three_channel_margin_mm": round(minimum, 4),
            "guard": "review_required" if reasons else "within_synthetic_fixture",
            "reasons": sorted(reasons),
        })
    return {
        "schema": SCHEMA,
        "scope": "hypothetical_readonly_fixed_root_swept_proximal_tail_and_neurovascular_tubes",
        "profile": profile, "frame_origin": origin,
        "source_authentication": "none",
        "frame_count": len(frames), "duration_s": round(frames[-1][0]-frames[0][0], 8),
        "fixed_tail_anchor_m": fixed_anchor,
        "first_alert_t_s": first_alert, "review_frame_count": alert_count,
        "worst_by_side": {
            side: {kind: {"margin_mm": value, "time_s": when}
                   for kind, (value, when) in values.items()}
            for side, values in worst.items()
        },
        "time_series": series,
        "tail_base_rotation": "root_fixed_yaw_of_synthetic_proximal_0.18m_segment_scaled_to_stature",
        "vessel_model": "fabricated_offsets_from_illustrative_pudendal_nerve_route",
        "full_tail_sweep_validated": False,
        "vascular_flow_or_tissue_compression_calculated": False,
        "anatomical_or_biological_safety_established": False,
        "native_cycles_caused": 0,
        "actuation_authorized": False,
        "sexual_state_inferred": False,
        "subjective_sensation_inferred": False,
    }
