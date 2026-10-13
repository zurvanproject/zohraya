"""Counterfactual checks of special-organ coupling using synthetic state only.

Run through ``run_tests.py --special`` to create defaults in an isolated tree.
No meal or drink is supplied; no canonical checkpoint is loaded or written.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

from synthetic_fixture import synthetic_body
from unified_body_v2 import UnifiedBody, digest, instant, native_total


def main():
    start = datetime.now(timezone.utc).isoformat()
    base = synthetic_body()
    records, checks = [], {}

    def check(name, condition):
        checks[name] = bool(condition)
        if not condition:
            raise AssertionError(name)

    def advance(body, name, external=None):
        result = body.cycle(
            event_id='special-' + str(body.revision + 1),
            at_utc=(instant(body.owner.wall_utc) + timedelta(seconds=.1)).isoformat(),
            duration_s=.1, external=external or {}, requested='observe',
            expected_revision=body.revision)
        records.append(dict(name=name, revision=body.revision,
            simulated_seconds=.1, owner_ticks=result['owner_ticks'],
            selected_action=result['owner']['selected_action'],
            audit=result['whole_body_audit'], special=result['outputs']['special'],
            native_energy_J=native_total(body.owner.owner.body)))
        check('conservation_' + name,
              result['whole_body_audit']['energy_error_J'] < 5e-5
              and result['whole_body_audit']['water_error_L'] < 1e-8
              and result['whole_body_audit']['light_error_J'] < 1e-8
              and result['whole_body_audit']['neural_clock_error_s'] < 1e-7)
        check('no_feeding_' + name,
              result['whole_body_audit']['meal_input_J'] == 0
              and result['whole_body_audit']['drink_input_L'] == 0
              and result['outputs']['gut']['total_absorbed_J'] == 0
              and result['outputs']['gut']['total_absorbed_water_L'] == 0)
        return result

    unknown = deepcopy(base)
    no_light = advance(unknown, 'unknown_light')
    check('missing_light_remains_unknown',
          no_light['outputs']['senses']['irradiance'] is None
          and no_light['whole_body_audit']['photochemical_J'] == 0)

    lit = deepcopy(base)
    light = advance(lit, 'declared_light', {'irradiance_w_m2': 1200})
    check('declared_light_has_bounded_capture',
          0 < light['whole_body_audit']['photochemical_J'] <= 1200 * .02 * .12 * .1)
    check('light_partition_accounts_for_rejection', all(
        abs(t['incident_J'] - t['photo_J'] - t['thermal_J'] - t['rejected_J']) < 1e-8
        and min(t['photo_J'], t['thermal_J'], t['rejected_J']) >= 0
        for t in light['trace']))

    isolated = deepcopy(base)
    isolated.disabled = sorted(set(isolated.disabled) | {'resonan_to_energy'})
    cut = advance(isolated, 'isolated_resonan', {'irradiance_w_m2': 1200})
    check('isolating_resonan_stops_capture_and_body_heating',
          cut['whole_body_audit']['photochemical_J'] == 0
          and cut['whole_body_audit']['external_heat_J'] == 0
          and all(abs(t['incident_J'] - t['rejected_J']) < 1e-8 for t in cut['trace']))

    hot = deepcopy(base)
    # Explicit counterfactual fixture change, not a real temperature reading.
    hot.owner.owner.body.state.heat_J = .6 * 195 * 3500
    blocked = advance(hot, 'hot_fixture', {'irradiance_w_m2': 1200})
    check('thermal_gate_prevents_additional_light_heat',
          blocked['outputs']['special']['shutter'] == 0
          and blocked['whole_body_audit']['photochemical_J'] == 0
          and blocked['whole_body_audit']['external_heat_J'] == 0)
    # Reset is deliberately labelled; it is not evidence of spontaneous recovery.
    hot.owner.owner.body.state.heat_J = 0
    reset = advance(hot, 'explicit_heat_reset', {'irradiance_w_m2': 1200})
    check('explicit_cooling_reset_reopens_capture', reset['whole_body_audit']['photochemical_J'] > 0)

    saturated = deepcopy(base)
    saturated.modules['special']['resonan_attention'] = 1
    sat = advance(saturated, 'saturated_fixture', {'irradiance_w_m2': 1200})
    check('saturation_reduces_accepted_energy',
          0 < sat['whole_body_audit']['photochemical_J']
          < light['whole_body_audit']['photochemical_J'])

    scarce = deepcopy(base)
    scarce.owner.owner.body.state.reserve_J = 50
    low = advance(scarce, 'small_reserve')
    check('azarine_ceiling_never_exceeds_actual_reserve',
          0 <= low['outputs']['special']['azarine_budget_J']
          <= scarce.owner.owner.body.state.reserve_J <= 50)

    # A labelled budget is a view of an existing stock, not another source.
    a, b = deepcopy(base), deepcopy(base)
    a.modules['special']['azarine_budget_J'] = 0
    b.modules['special']['azarine_budget_J'] = 7200
    ra, rb = advance(a, 'budget_label_zero'), advance(b, 'budget_label_ceiling')
    check('budget_label_cannot_create_energy',
          a.owner.body() == b.owner.body()
          and ra['whole_body_audit'] == rb['whole_body_audit'])
    check('spandar_tracks_executed_memory_and_prediction_error',
          rb['outputs']['special']['spandar_digest'] == digest(b.owner.aux['body_memory'])
          and rb['outputs']['special']['spandar_last_error']
          == rb['owner']['prediction']['mean_scaled_absolute_error'])

    t = base.owner.owner.body.state.time_s
    expired = deepcopy(base)
    old = advance(expired, 'expired_sensory_evidence', {'sensors': {'vision': dict(
        value=1, source_id='synthetic-special-check', sampled_at_s=t-6,
        kind='declared_simulated_input')}})
    check('expired_vision_stays_expired', 'vision' in old['outputs']['senses']['expired'])

    restored = UnifiedBody.restore(json.loads(json.dumps(lit.checkpoint(), sort_keys=True)))
    resumed_a = advance(lit, 'continuous_after_light')
    resumed_b = advance(restored, 'restored_after_light')
    check('cold_continuation_matches_receipt_and_checkpoint',
          resumed_a == resumed_b and lit.checkpoint() == restored.checkpoint())
    check('light_is_not_reused_when_next_input_omits_it',
          resumed_a['outputs']['senses']['irradiance'] is None
          and resumed_a['whole_body_audit']['photochemical_J'] == 0)

    print(json.dumps(dict(schema='tadash-special-coordination-checks/1',
        start_utc=start, end_utc=datetime.now(timezone.utc).isoformat(),
        checks=checks, checks_passed=sum(checks.values()), checks_total=len(checks),
        cycles_executed=len(records), simulated_seconds=sum(r['simulated_seconds'] for r in records),
        warmup_seconds=7, canonical_state_loaded=False, canonical_state_modified=False,
        new_food_or_drink_supplied=False, runtime_equations_changed=False,
        biological_validation=False, background_execution_started=False,
        limitations=['Combined light-control model; no independent left/right lobes',
                     'Spandar is a digest/error monitor, not crystal-tissue dynamics',
                     'Azarine is a tagged reserve ceiling, not a separate thermal store',
                     'Cooling recovery here is an explicit fixture reset'],
        records=records), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
