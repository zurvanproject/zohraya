"""Reproducible paired interventions on freshly generated, explicitly enabled bodies."""
from copy import deepcopy
from datetime import timedelta
import json

from synthetic_fixture import synthetic_body
from unified_body_v2 import instant


def advance(body, inputs=None, seconds=.1, light=None):
    external = {"special_physiology": inputs or {}}
    if light is not None:
        external["irradiance_w_m2"] = light
    return body.cycle(event_id="physiology-" + str(body.revision + 1),
        at_utc=(instant(body.owner.wall_utc) + timedelta(seconds=seconds)).isoformat(),
        duration_s=seconds, external=external, requested="observe",
        expected_revision=body.revision)


def main():
    base = synthetic_body()
    base.enable_special_physiology()
    rows = []

    def step(body, name, inputs=None, seconds=.1, light=None):
        result = advance(body, inputs, seconds, light)
        rows.append(dict(name=name, simulated_seconds=seconds, revision=body.revision,
            audit=result["whole_body_audit"], special=result["outputs"]["special"],
            fuel_J=body.owner.owner.body.state.fuel_J,
            reserve_J=body.owner.owner.body.state.reserve_J))
        return result

    step(deepcopy(base), "bilateral", {"resonan": {"left": {"strain": 1}, "right": {"strain": 1}}}, light=1200)
    step(deepcopy(base), "left_perfusion_loss", {"resonan": {"left": {"strain": 1, "perfusion": 0}, "right": {"strain": 1}}}, light=1200)
    sp = deepcopy(base)
    step(sp, "spandar_funded")
    step(sp, "spandar_support_loss", {"spandar_perfusion": 0}, seconds=2)
    step(sp, "spandar_support_return")
    hot = deepcopy(base)
    step(hot, "azarine_load", {"azarine_load_W": 40}, seconds=10)
    step(hot, "azarine_passive_recovery", seconds=10)
    cold = deepcopy(base)
    step(cold, "paired_baseline", seconds=10)
    hot_r, recovered = rows[5]["special"]["tissue"]["azarine"], rows[6]["special"]["tissue"]["azarine"]
    checks = dict(
        unilateral_input_preserves_other_side=rows[1]["special"]["tissue"]["resonan"]["left"]["signal"] == 0
            and rows[1]["special"]["tissue"]["resonan"]["right"]["signal"] > 0,
        spandar_stops_and_recovers=not rows[3]["special"]["tissue"]["spandar"]["valid"]
            and rows[4]["special"]["tissue"]["spandar"]["valid"],
        local_heating_reduces_admitted_load=hot_r["thermal_gate"] < 1,
        spontaneous_cooling_without_temperature_reset=recovered["local_temperature_C"] < hot_r["local_temperature_C"],
        energy_conserved=all(r["audit"]["energy_error_J"] < 5e-5 for r in rows),
        water_conserved=all(r["audit"]["water_error_L"] < 1e-8 for r in rows),
        partition_conserved=all(r["special"]["tissue"]["azarine"]["partition_error_J"] < 1e-8 for r in rows))
    result = dict(schema="nasuraya-special-physiology-demo/1", checks=checks,
        checks_passed=sum(checks.values()), checks_total=len(checks),
        host_mass_kg=195, host_height_cm=250, proposed_morphology_executed=False,
        canonical_state_loaded=False, external_api_used=False, biological_validation=False,
        simulated_seconds=sum(r["simulated_seconds"] for r in rows),
        independent_fixture_warmup_seconds=7, records=rows)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
