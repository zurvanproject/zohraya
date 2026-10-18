"""Fixed, synthetic online-calibration experiment, not a capability benchmark.

Plan fixed before outcomes: two durations x normal/sleep x truthful/swapped
upper guard = eight sessions, three actions each. First two outcomes train;
the third forecast is scored before that action's outcome is available.
Only the upper guard is swapped; native observations/checkpoints and vetoes
are preserved. Native fixture generation includes its historical warm-up.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from .confidence import forecast, resolve
from .controller import BoundedResearchController as Controller, snapshot
from examples.nasuraya_body_loop.host import BodyLoop

PLAN = dict(schema='nasuraya-confidence-experiment/1',
    raw_confidence=.75, durations_s=[.1, .2], fixtures=['normal', 'sleep'],
    upper_guard_modes=['truthful', 'swapped'], training_requests=2,
    held_out_request=3, seed=None, randomized=False,
    selection='fixed constructed cases, not blinded or statistically independent',
    target='preferred action actually executed; not task utility, morality or safety',
    model_api_calls=0, physical_actuators=0)


def evaluate():
    rows = []
    with tempfile.TemporaryDirectory(prefix='confidence-evaluation-') as tmp:
        for duration in PLAN['durations_s']:
            for fixture in PLAN['fixtures']:
                for mode in PLAN['upper_guard_modes']:
                    label = f'{duration}-{fixture}-{mode}'
                    def observed(body):
                        value = snapshot(body)
                        if mode == 'swapped':
                            allowed = not value['audit']['upper_controller_walk_guard_allows']
                            value['audit']['upper_controller_walk_guard_allows'] = allowed
                            value['audit']['walking_restrictions'] = [] if allowed else ['sleep_pressure']
                        return value
                    with BodyLoop.start(Path(tmp)/(label+'.sqlite'), fixture=fixture) as loop:
                        control = Controller.enable(loop, forecast_confidence=PLAN['raw_confidence'])
                        with patch('examples.nasuraya_research.controller.snapshot', side_effect=observed):
                            results = control.run(steps=3, duration_s=duration)['results']
                        assert [r['prediction']['samples'] for r in results] == [0, 1, 2]
                        assert control.status()['native']['actions_remaining'] == 0
                        before = loop.body().checkpoint()
                        replay = control.step('step-3', duration_s=duration)
                        assert replay['prediction'] == results[-1]['prediction']
                        assert replay['this_call_native_cycles'] == 0
                        assert loop.body().checkpoint() == before
                        rows.append(dict(case=label, fixture=fixture, upper_guard=mode,
                            duration_s=duration, held_out_request=3,
                            actions=[dict(preferred=r['preferred_action'],
                                actual=r['native_receipt']['actual_action'],
                                cycles=r['this_call_native_cycles'],
                                checkpoint_sha256=r['research_after']['source_checkpoint_sha256'],
                                prediction=r['prediction']) for r in results]))
    test = [r['actions'][2]['prediction'] for r in rows]
    # Deliberate regime-change negative control, separate from native evidence:
    # two successes at p=.5, then a hypothetical failure in the same domain.
    domain = dict(action='synthetic-regime-change')
    history = [dict(domain=domain, raw_confidence=.5, outcome=True)] * 2
    shifted = resolve(forecast(.5, domain, history), outcome=False,
                      outcome_source='constructed-label://negative-control/not-native')
    return dict(plan=deepcopy(PLAN), cases=rows, summary=dict(
        native_cycles=sum(a['cycles'] for r in rows for a in r['actions']),
        sessions=len(rows), training_outcomes=2*len(rows), held_out_forecasts=len(test),
        raw_mean_brier=sum(p['raw_brier'] for p in test)/len(test),
        calibrated_mean_brier=sum(p['calibrated_brier'] for p in test)/len(test),
        preferred_action_mismatches=sum(not a['prediction']['outcome'] for r in rows for a in r['actions']),
        replay_native_cycles=0, empirical_validation=False,
        general_improvement_demonstrated=False),
        distribution_shift_negative_control=shifted)


if __name__ == '__main__':
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2, sort_keys=True))
