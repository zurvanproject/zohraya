"""Two bounded native body cases, followed by affect-only counterfactual replay."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from .appraisal import digest, native_affect, preview_stored


def run():
    native=native_affect()
    from examples.nasuraya_body_loop.host import BodyLoop
    from examples.nasuraya_research.controller import BoundedResearchController, snapshot
    results=[]
    for case in ('normal', 'sleep_with_fault_injected_planner'):
        with tempfile.TemporaryDirectory() as tmp, BodyLoop.start(Path(tmp)/'body.sqlite',
                fixture='normal' if case=='normal' else 'sleep',max_actions=1) as loop:
            controller=BoundedResearchController.enable(loop,forecast_confidence=.95)
            if case=='normal':
                recorded=controller.step('probe')
            else:
                def optimistic(body):
                    observation=snapshot(body)
                    observation['audit']['upper_controller_walk_guard_allows']=True
                    observation['audit']['walking_restrictions']=[]
                    return observation
                # Deliberate planner fault, not a relaxation of native body veto.
                with patch('examples.nasuraya_research.controller.snapshot',side_effect=optimistic):
                    recorded=controller.step('probe')
            checkpoint=deepcopy(loop.body().checkpoint()); status=controller.status()
            pairs=[]
            for joy in (0.,1.):
                start=native.initial_state();start['affect']['joy']=joy
                on=preview_stored(controller,'probe',start)
                off=preview_stored(controller,'probe',start,affect_enabled=False)
                assert on['evidence']==off['evidence']
                pairs.append(dict(initial_joy=joy,plan=on['record']['plan']['action'],
                    plan_without_affect=off['record']['plan']['action'],
                    evidence=on['evidence'],affect_after={k:on['state']['affect'][k]
                        for k in ('joy','surprise','disappointment','relief','calm')},
                    causal_plan_change=on['record']['causal_choice_change']))
            assert loop.body().checkpoint()==checkpoint and controller.status()==status
            results.append(dict(case=case,actual_action=recorded['native_receipt']['actual_action'],
                native_cycles=recorded['historical_native_cycles'],body_unchanged_by_affect_replay=True,
                remaining_actions=controller.status()['native']['actions_remaining'],pairs=pairs,
                native_checkpoint_sha256=checkpoint['sha256']))
    assert results[0]['actual_action']=='walk'
    assert results[1]['actual_action']=='protect'
    assert all(r['plan']=='verify' for r in results[1]['pairs'])
    result=dict(schema='nasuraya-evidence-appraisal-evaluation/1',cases=results,
        total_native_cycles=sum(r['native_cycles'] for r in results),
        additional_body_cycles_from_affect=0,model_api_calls=0,
        canonical_state_changed=False,decision_writeback=False,
        scope='two constructed native-body cases and eight affect-only replays; not general performance or subjective feeling')
    print(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))
    return result

if __name__=='__main__':
    run()
