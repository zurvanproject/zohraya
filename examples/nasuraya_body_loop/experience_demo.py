"""Finite native-body demonstration, including reopen and feature ablations."""
from copy import deepcopy
import json
from .experience import ExperienceController, plan
from .host import BodyLoop


def demo(output):
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    sessions = {}
    for fixture in ('normal', 'sleep'):
        path = output/(fixture+'.sqlite')
        with BodyLoop.start(path, fixture=fixture, max_actions=3) as loop:
            c = ExperienceController.enable(loop)
            first = c.step('first')
            snapshot = loop.observe(); state = c.status()['state']
            policies = {}
            for flag in ('none', 'affect', 'prediction', 'memory'):
                variant = deepcopy(state)
                if flag != 'none': variant['flags'][flag] = False
                policies[flag] = plan(variant, snapshot, .1)
            c.consolidate()
            saved = c.status()['state']
        with BodyLoop(path) as loop:
            c = ExperienceController(loop)
            assert c.status()['state'] == saved
            second = c.step('second'); third = c.step('third')
            consolidated = c.consolidate()
            assert loop.status()['actions_remaining'] == 0
            assert c.step('first')['this_call_native_cycles'] == 0
            sessions[fixture] = dict(events=[first, second, third],
                matched_observation_ablations=policies, cold_reopen_equal=True,
                consolidation=consolidated, final_status=c.status())
    assert sessions['sleep']['events'][0]['native_receipt']['actual_action'] == 'protect'
    assert sessions['sleep']['events'][1]['plan']['preferred'] == 'observe'
    summary = dict(scope='constructed native software-body demonstration, not a general capability benchmark',
                   native_cycles=6, sessions=sessions, model_api_calls=0)
    (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    return summary
