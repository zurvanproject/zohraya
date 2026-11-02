"""Kimia-ye Khak: epistemic contract for FIRST TOUCH, not a sensor or feeling.

A verified poetic anchor from Rumi's Divan-e Shams provides a design metaphor.
Only measured, provenance-labelled contact observations can support claims
about the limited simulated body. Unknown surfaces MUST remain unknown.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

CHARTER = Path(__file__).resolve().parents[1] / "docs" / "tadash-kimia-khak-contract-v01.json"
PROVENANCE = {"native_mujoco", "synthetic_fixture"}
FIELDS = {"schema", "event_id", "provenance", "contact", "left_foot_force_n",
          "right_foot_force_n", "slip_m_per_s", "surface"}
LABELS = {"unspecified", "flat_simulated_floor"}
MAX_FORCE_N = 5000.
MAX_SLIP_M_PER_S = 10.


def load_charter(path=CHARTER):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    anchor = d.get("literary_anchor", {})
    if (d.get("schema") != "tadash-kimia-khak-charter/1" or
            anchor.get("work") != "دیوان شمس" or anchor.get("ghazal") != 473 or
            anchor.get("verse") != ["ای خنک آن جان و دل کو رهد از آب و گل",
                                    "گرچه در این آب و گل دستگه کیمیاست"] or
            d.get("phase") != "design_only_no_soil_sensor_enabled" or
            d.get("grounding_rules", {}).get("physical_soil_touch_claim_without_physical_sensor") is not False or
            d.get("grounding_rules", {}).get("new_action_from_this_charter") is not False):
        raise ValueError("Unsupported or modified poetry/sensing contract")
    return d


def finite_number(x, label, upper):
    if type(x) not in (float, int) or not math.isfinite(x) or not 0 <= x <= upper:
        raise ValueError(f"{label} must be finite and in declared range")
    return float(x)


def observe(event, charter=None):
    """Read-only interpretation with epistemic abstention, no inferred soil texture."""
    c = load_charter() if charter is None else charter
    if c.get("phase") != "design_only_no_soil_sensor_enabled":
        raise ValueError("Unknown charter activation status")
    if type(event) is not dict or set(event) != FIELDS:
        raise ValueError("Unexpected or missing observation fields")
    if event["schema"] != "tadash-contact-observation/1":
        raise ValueError("Unknown observation schema")
    if type(event["event_id"]) is not str or not (1 <= len(event["event_id"]) <= 64):
        raise ValueError("Missing observation identity")
    if event["provenance"] not in PROVENANCE:
        raise ValueError("Unverified observation provenance")
    if type(event["contact"]) is not bool or event["surface"] not in LABELS:
        raise ValueError("Invalid contact or unsupported terrain tag")
    left = finite_number(event["left_foot_force_n"], "left force", MAX_FORCE_N)
    right = finite_number(event["right_foot_force_n"], "right force", MAX_FORCE_N)
    slip = finite_number(event["slip_m_per_s"], "slip speed", MAX_SLIP_M_PER_S)
    loaded = bool(event["contact"] and left > 1 and right > 1)
    if loaded and event["surface"] == "flat_simulated_floor":
        claim = "bilateral_load_on_declared_simulated_floor"
    elif event["contact"] and (left > 0 or right > 0):
        claim = "limited_contact_reported"
    else:
        claim = "contact_not_supported"
    return {
        "schema": "tadash-contact-interpretation/1",
        "event_id": event["event_id"],
        "origin": event["provenance"],
        "contact_claim": claim if event["provenance"] == "native_mujoco" else "synthetic_fixture_only",
        "measured": {"left_force_n": left, "right_force_n": right, "slip_m_per_s": slip},
        "unknown": ["soil_type", "grain_size", "moisture", "texture", "felt_touch"],
        "physical_soil_touch_established": False,
        "conscious_tactile_sensation_established": False,
        "motor_commands_emitted": 0,
        "next_research_question": "Can a native pressure/contact or terrain model distinguish surfaces without label leakage?"
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation-json", type=Path, required=True)
    opts = parser.parse_args()
    datum = json.loads(opts.observation_json.read_text(), parse_constant=lambda _:
                       (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    print(json.dumps(observe(datum), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
