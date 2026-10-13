"""Synthetic longitudinal checks; run through run_tests.py --endurance.

Actual trajectory: 200 one-second cycles, 2,000 native ticks, 400,000 neural
ticks, plus an explicitly separate seven-second fixture warm-up. No saved user
state is read. Cold continuation probes run on clones and are counted separately.
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback

from synthetic_fixture import synthetic_body
from unified_body_v2 import UnifiedBody, ROOT, digest, instant
from audit_self_model import assess

PHASES = ('baseline', 'fresh_sensors', 'lung_reduction', 'lung_recovery',
          'kidney_reduction', 'meal_water_light', 'motion_and_disturbance', 'recovery')


def event_for(body, index, cycles_per_phase):
    phase = PHASES[(index - 1) // cycles_per_phase]
    external = {}
    action = 'observe'
    local = (index - 1) % cycles_per_phase
    if phase == 'fresh_sensors':
        external = {'sensors': {'touch': dict(value=.2 + .1 * (local % 3),
            source_id='synthetic-endurance', sampled_at_s=body.owner.owner.body.state.time_s,
            kind='declared_simulated_input')}}
    elif phase == 'lung_reduction':
        external = {'capacities': {'lung': .2}}
    elif phase == 'kidney_reduction':
        external = {'capacities': {'kidney': .2}}
    elif phase == 'meal_water_light':
        external = {'irradiance_w_m2': 600., 'void_permitted': True}
        if local % 5 == 0:
            external.update(meal_J=10000., drink_L=.2)
    elif phase == 'motion_and_disturbance':
        external = {'native': {'upper_targets': {'shoulder_L': .2 * (local % 2),
                                                 'elbow_L': .2 * (local % 2)}}}
        if local % 5 == 0:
            external['native']['unexpected_impulse_N_s'] = [2., 0.]
        action = 'walk' if local % 3 == 0 else 'observe'
    elif phase == 'recovery':
        external = {'void_permitted': True}
        action = 'rest'
    # Deliberately nonlexical IDs exercise cache chronology after JSON sorting.
    return dict(event_id=f'endurance-{digest(index)[:12]}-{index}',
        at_utc=(instant(body.owner.wall_utc) + timedelta(seconds=1)).isoformat(),
        duration_s=1., external=external, requested=action,
        expected_revision=body.revision), phase


def reject_without_mutation(body, event, message=None):
    before = body.checkpoint()
    try:
        body.cycle(**event)
    except ValueError as error:
        if message is not None:
            assert message in str(error), str(error)
    else:
        raise AssertionError('invalid event accepted')
    assert body.checkpoint() == before, 'rejection mutated state'


def cold_probe(body, probe_index, directory):
    directory = directory / str(probe_index)
    directory.mkdir()
    path = directory / 'synthetic_checkpoint.json'
    # A new file is a new synthetic snapshot, not the live writer's leased path.
    # The child changes only this clone's file; the trajectory keeps its lease.
    snapshot = deepcopy(body)
    snapshot.loaded_sha256 = None
    snapshot.save(path)
    loaded = UnifiedBody.load(path)
    assert loaded.checkpoint() == body.checkpoint(), 'save/load differs'
    event = dict(event_id=f'cold-probe-{probe_index}',
        at_utc=(instant(body.owner.wall_utc) + timedelta(seconds=.1)).isoformat(),
        duration_s=.1, external={}, requested='observe', expected_revision=body.revision)
    expected = deepcopy(body)
    receipt = expected.cycle(**event)
    event_path = directory / 'event.json'
    output_path = directory / 'receipt.json'
    event_path.write_text(json.dumps(event))
    process = subprocess.run([sys.executable, str(ROOT / 'unified_body_v2.py'),
        'step', '--state', str(path), '--event', str(event_path), '--output', str(output_path)],
        capture_output=True, text=True, timeout=120)
    assert process.returncode == 0, process.stderr
    assert json.loads(output_path.read_text()) == receipt, 'cold receipt differs'
    assert UnifiedBody.load(path).checkpoint() == expected.checkpoint(), 'cold state differs'
    return dict(at_revision=body.revision, file_bytes=path.stat().st_size,
                exact_roundtrip=True, exact_cold_receipt=True,
                exact_cold_state=True, clone_simulated_seconds=.1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycles-per-phase', type=int, default=25)
    parser.add_argument('--output', type=Path, default=Path('endurance_results.json'))
    args = parser.parse_args()
    if not 3 <= args.cycles_per_phase <= 500:
        parser.error('cycles per phase must be 3..500')
    start = time.monotonic()
    body = synthetic_body()
    origin_time = body.owner.owner.body.state.time_s
    origin_ticks = body.owner.owner.renal.state['ticks']
    initial_neural_ticks = body.modules['neural']['integration_ticks']
    steps = []
    cold = []
    rejection_count = replay_count = 0
    first_event = None
    failure = None
    stage = 'initialization'
    phase_stats = {name: [] for name in PHASES}
    cumulative_energy = cumulative_water = 0.
    total = args.cycles_per_phase * len(PHASES)
    try:
        with tempfile.TemporaryDirectory(prefix='tadash-cold-') as directory:
            for index in range(1, total + 1):
                event, phase = event_for(body, index, args.cycles_per_phase)
                stage = f'cycle:{index}:{phase}'
                if first_event is None:
                    first_event = deepcopy(event)
                result = body.cycle(**event)
                audit = result['whole_body_audit']
                assert result['owner_ticks'] == 10
                assert result['owner']['physical_model_valid'], 'physical model entered failed state'
                assert len(body.bus) == 97
                assert {p['system_stage'] for p in body.bus} == set(range(1, 13))
                assert all(p['sampled_at_s'] == body.owner.owner.body.state.time_s for p in body.bus)
                assert audit['energy_error_J'] < 5e-5
                assert audit['water_error_L'] < 1e-8
                assert audit['light_error_J'] < 1e-8
                assert audit['neural_clock_error_s'] < 1e-7
                stocks = body.owner.body()['finite_stocks']
                assert all(math.isfinite(v) and v >= 0 for v in stocks.values())
                cumulative_energy += audit['energy_error_J']
                cumulative_water += audit['water_error_L']
                respiration = body.owner.physical.last['respiration']['ledger']
                row = dict(cycle=index, phase=phase, revision=body.revision,
                    time_s=body.owner.owner.body.state.time_s,
                    selected_action=result['owner']['selected_action'],
                    requested_action=event['requested'],
                    stocks=stocks, energy_error_J=audit['energy_error_J'],
                    water_error_L=audit['water_error_L'],
                    neural_clock_error_s=audit['neural_clock_error_s'],
                    uptake_L=respiration['uptake_L'],
                    cleared_co2_L=respiration['cleared_co2_L'],
                    filtered_L=body.owner.owner.renal.state['filtered_L'],
                    prediction_error=result['owner']['prediction']['mean_scaled_absolute_error'],
                    fresh_sensory_channels=assess(body)['available_sensory_channels'],
                    record_counts=dict(journal=len(body.journal),requests=len(body.requests),
                        results=len(body.results),episodes=len(body.episodes),
                        bank_episodes=len(body.owner.owner.memory.memory.episodes)))
                steps.append(row)
                phase_stats[phase].append(row)
                if index % args.cycles_per_phase == 0:
                    stage = f'replay:{index}'
                    before = body.checkpoint()
                    assert body.cycle(**event) == result
                    assert body.checkpoint() == before
                    replay_count += 1
                    bad = event | {'event_id': f'invalid-{index}',
                                   'external': {'drink_L': float('nan')}}
                    reject_without_mutation(body, bad)
                    rejection_count += 1
                    if index > 16:
                        reject_without_mutation(body, first_event, 'archived')
                        rejection_count += 1
                    if (index // args.cycles_per_phase) % 2 == 0:
                        stage = f'cold-continuation:{index}'
                        cold.append(cold_probe(body, index, Path(directory)))
                    print(json.dumps(dict(progress=index,total=total,phase=phase,
                        elapsed_s=round(time.monotonic()-start,2),
                        fuel_J=stocks['fuel_J'],cold_probes=len(cold))), flush=True)
    except Exception as error:
        failure = dict(stage=stage,type=type(error).__name__,message=str(error),
                       traceback=traceback.format_exc())
    checks = dict(trajectory_completed=len(steps) == total and failure is None,
                  exact_cold_continuation=len(cold) == 4 and all(x['exact_cold_state'] for x in cold),
                  recent_replay_transactional=replay_count == 8,
                  invalid_and_archived_events_rejected=rejection_count ==
                      8 + sum(i * args.cycles_per_phase > 16 for i in range(1,9)))
    if failure is None:
        checks.update(native_ticks_exact=body.owner.owner.renal.state['ticks']-origin_ticks == total*10,
            neural_ticks_exact=body.modules['neural']['integration_ticks']-initial_neural_ticks == total*2000,
            simulated_duration_exact=abs(body.owner.owner.body.state.time_s-origin_time-total)<1e-8,
            bounded_results=len(body.results)<=16,
            bounded_recent_episodes=len(body.episodes)<=128,
            sensory_expired_in_final_recovery=not assess(body)['available_sensory_channels'],
            uptake_returns_after_lung_reduction=phase_stats['lung_recovery'][-1]['uptake_L']>
                phase_stats['lung_reduction'][-1]['uptake_L'],
            final_state_restore_exact=UnifiedBody.restore(body.checkpoint()).checkpoint()==body.checkpoint())
    summary=dict(schema='tadash-endurance/1',
        executed_utc=datetime.now(timezone.utc).isoformat(),elapsed_wall_s=time.monotonic()-start,
        fixture='synthetic defaults; no user checkpoint loaded',
        planned_cycles=total,completed_cycles=len(steps),
        completed_simulated_seconds=body.owner.owner.body.state.time_s-origin_time,
        actual_native_ticks=body.owner.owner.renal.state['ticks']-origin_ticks,
        actual_neural_ticks=body.modules['neural']['integration_ticks']-initial_neural_ticks,
        fixture_warm_up_seconds=7.,cold_probes=cold,
        checks=checks,passed=all(checks.values()) and failure is None,failure=failure,
        max_energy_error_J=max((x['energy_error_J'] for x in steps),default=0),
        max_water_error_L=max((x['water_error_L'] for x in steps),default=0),
        max_neural_clock_error_s=max((x['neural_clock_error_s'] for x in steps),default=0),
        sum_absolute_energy_residuals_J=cumulative_energy,
        sum_absolute_water_residuals_L=cumulative_water,
        actions=dict(Counter(x['selected_action'] for x in steps)),
        steps=steps,empirical_validation=False,parameter_learning_tested=False,
        background_execution_started=False,canonical_state_modified=False)
    args.output.write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='steps'}),flush=True)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
