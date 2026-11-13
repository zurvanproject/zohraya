"""Bounded, offline Tadash BODY research microbench (not physiology/gait validation).

Two explicitly limited tools: a toe contact support-polygon diagnostic and a
zero-dimensional cardiorespiratory algebraic teaching surrogate. Neither is
connected to a native controller, physical sensors, or a living organism.
"""
from __future__ import annotations

import argparse
import json
import math
from collections.abc import Mapping, Sequence


def _finite(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def _hull(points):
    points = sorted(set(points))
    lower, upper = [], []
    for p in points:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(points):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _distance_to_segment(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    span = dx*dx + dy*dy
    fraction = max(0.0, min(1.0, ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/span))
    return math.hypot(p[0]-(a[0]+fraction*dx), p[1]-(a[1]+fraction*dy))


def support_margin(contacts: Sequence[Mapping], com_xy, *, min_contact_n=1.0):
    """Planar signed COM margin from *provided* toe pad contact samples.

    Positive means the COM projection is within the geometric contact hull;
    negative means outside. This is NOT a dynamic stability, running or
    collision-safety certification. Return unknown on inadequate contacts.
    """
    if not isinstance(contacts, (tuple, list)) or len(contacts) > 64:
        raise ValueError("contacts must be a bounded list")
    if not isinstance(com_xy, (tuple, list)) or len(com_xy) != 2:
        raise ValueError("COM must be an (x, y) pair")
    p = (_finite(com_xy[0], "com_x"), _finite(com_xy[1], "com_y"))
    threshold = _finite(min_contact_n, "contact threshold")
    if threshold <= 0:
        raise ValueError("threshold must be positive")
    active = []
    names = set()
    for c in contacts:
        if not isinstance(c, Mapping) or set(c) != {"pad", "x_m", "y_m", "normal_n"}:
            raise ValueError("invalid contact schema")
        name = c["pad"]
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("invalid or duplicate pad id")
        names.add(name)
        xy = (_finite(c["x_m"], "x_m"), _finite(c["y_m"], "y_m"))
        force = _finite(c["normal_n"], "normal_n")
        if force < 0:
            raise ValueError("negative normal load")
        if force >= threshold:
            active.append(xy)
    result = {
        "evidence": "provided_contact_geometry_only",
        "validated_dynamic_gait": False,
        "active_pad_count": len(active),
        "signed_margin_m": None,
        "support_area_m2": None,
        "status": "insufficient_support_geometry",
    }
    if len(set(active)) < 3:
        return result
    polygon = _hull(active)
    if len(polygon) < 3:
        return result
    area = abs(sum(a[0]*b[1]-a[1]*b[0]
                   for a,b in zip(polygon, polygon[1:]+polygon[:1]))) / 2.0
    if area <= 1e-12:
        return result
    inside = all(_cross(a, b, p) >= -1e-12
                 for a,b in zip(polygon, polygon[1:]+polygon[:1]))
    margin = min(_distance_to_segment(p,a,b)
                 for a,b in zip(polygon, polygon[1:]+polygon[:1]))
    result.update({"signed_margin_m": round(margin if inside else -margin, 9),
                   "support_area_m2": round(area, 9),
                   "status": "com_inside_contact_hull" if inside else "com_outside_contact_hull"})
    return result


def cardiopulmonary_0d(inputs: Mapping):
    """Simple CO/MAP/alveolar-gas equations, with *authored* inputs only.

    No baroreflex, circulation, gas diffusion, shunt, SpO2 or time integration.
    Units: bpm, mL, mmHg min/L, mmHg, mL/min, fractional FiO2.
    """
    limits = {
        "hr_bpm": (1, 240), "sv_ml": (1, 250), "svr_mmHg_min_per_l": (.01, 80),
        "cvp_mmHg": (-5, 40), "rr_min": (1, 80), "vt_ml": (1, 3000),
        "dead_space_ml": (0, 1000), "vco2_ml_min": (1, 1000),
        "fio2": (.15, 1.0), "pb_mmHg": (350, 800), "rq": (.6, 1.3),
    }
    if not isinstance(inputs, Mapping) or set(inputs) != set(limits):
        raise ValueError("missing or extra cardiopulmonary input")
    v = {key: _finite(inputs[key],key) for key in limits}
    if any(not (low <= v[key] <= high) for key,(low,high) in limits.items()):
        raise ValueError("input outside declared bounded domain")
    if v["dead_space_ml"] >= v["vt_ml"]:
        raise ValueError("dead space must be less than tidal volume")
    co = v["hr_bpm"]*v["sv_ml"]/1000.0
    map_mmHg = v["cvp_mmHg"]+co*v["svr_mmHg_min_per_l"]
    va_l_min = v["rr_min"]*(v["vt_ml"]-v["dead_space_ml"])/1000.0
    paco2 = .863*v["vco2_ml_min"]/va_l_min
    pao2 = v["fio2"]*(v["pb_mmHg"]-47.0)-paco2/v["rq"]
    if pao2 < 0:
        raise ValueError("negative surrogate alveolar PO2")
    return {
        "evidence": "algebraic_0d_fixture_only",
        "source": "authored_research_inputs_not_measurements",
        "predicted_spo2": None,
        "predicted_arterial_pressure_waveform": None,
        "validated_biological_physiology": False,
        "co_l_min": round(co,6), "map_proxy_mmHg": round(map_mmHg,6),
        "alveolar_ventilation_l_min": round(va_l_min,6),
        "alveolar_pco2_proxy_mmHg": round(paco2,6),
        "alveolar_po2_proxy_mmHg": round(pao2,6),
    }


def evidence_card():
    """Avoid presenting generated-image vitals or progress as telemetry."""
    return {
        "body_completion_percent": None,
        "visual_image_percent_is_evidence": False,
        "areas": {
            "neural_proprioception": "native_simulated_research_PR_206_to_209_not_external_sensor",
            "digitigrade_running": "not_validated_contact_margin_only",
            "cardiopulmonary": "not_validated_0d_fixture_only",
            "dios_embodiment": "incomplete_research_one_way_ingress_PR_205",
        },
        "no_physical_sensor_or_actuator": True,
    }


EXAMPLE_CONTACTS = [
    {"pad": "L1", "x_m": -.12, "y_m": -.07, "normal_n": 15.0},
    {"pad": "L2", "x_m": .08, "y_m": -.07, "normal_n": 15.0},
    {"pad": "L3", "x_m": .02, "y_m": .02, "normal_n": 15.0},
    {"pad": "R1", "x_m": -.12, "y_m": .07, "normal_n": 15.0},
    {"pad": "R2", "x_m": .08, "y_m": .07, "normal_n": 15.0},
    {"pad": "R3", "x_m": .02, "y_m": -.02, "normal_n": 15.0},
]
EXAMPLE_CP = {
    "hr_bpm": 60, "sv_ml": 75, "svr_mmHg_min_per_l": 16,
    "cvp_mmHg": 5, "rr_min": 12, "vt_ml": 500,
    "dead_space_ml": 150, "vco2_ml_min": 200,
    "fio2": .21, "pb_mmHg": 760, "rq": .8,
}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="optional path for JSON, no network or server writes")
    args=parser.parse_args()
    report={"contact":support_margin(EXAMPLE_CONTACTS,(0.0,0.0)),
            "cardiopulmonary":cardiopulmonary_0d(EXAMPLE_CP),
            "readiness":evidence_card(),
            "fixture_only":True}
    rendered=json.dumps(report,indent=2,ensure_ascii=False,sort_keys=True)+"\n"
    if args.output:
        from pathlib import Path
        target=Path(args.output)
        if target.exists():
            raise SystemExit("Refusing to overwrite an existing report")
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(rendered,encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
