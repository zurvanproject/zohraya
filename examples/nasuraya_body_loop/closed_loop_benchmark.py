"""Precommitted independent trajectories and paired forecasts on both paths."""
from copy import deepcopy
from datetime import datetime,timedelta
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from synthetic_fixture import synthetic_origin
from unified_body_v2 import PersistentEmbodiment,UnifiedBody
from .adaptive_memory import (AdaptiveMemory,ALPHA,DELTA_LIMIT,ERROR_FLOOR,initial_model,
                              forecast,errors,validate_model,state)
from .closed_loop import FrozenClosedLoop
from .host import BodyLoop
from .self_maintenance import digest

PROTOCOL=Path(__file__).with_name('closed_loop_protocol.json')


def fixture(case):
    owner=PersistentEmbodiment.restore(synthetic_origin())
    before=owner.body()
    owner.aux['sleep_pressure']=case['sleep_pressure']
    owner.aux['muscle_tone']=case['muscle_tone']
    owner._record(before,owner.body(),'external_input','precommitted held-out synthetic sleep/tone fixture',0.)
    body=UnifiedBody.migrate(owner.checkpoint())
    body.migration['closed_loop_fixture']={k:case[k] for k in ('id','sleep_pressure','muscle_tone','warmup_walks')}
    for i in range(case['warmup_walks']):
        at=(datetime.fromisoformat(body.owner.wall_utc)+timedelta(seconds=.1)).isoformat()
        body.cycle(event_id='fixture-warmup-'+str(i),at_utc=at,duration_s=.1,requested='walk',external={})
    # Warm-up is fixture construction, identical for both arms, not test-goal budget.
    return body


def start_from(path,body):
    envelope=body.checkpoint()
    with patch('examples.nasuraya_body_loop.host.synthetic_body',side_effect=lambda:UnifiedBody.restore(envelope)):
        return BodyLoop.start(path,max_actions=3)


def train(out,cases):
    models={'A':initial_model(),'B':initial_model()};sources=[];observed_states=set()
    for i,case in enumerate(cases):
        arms={}
        for arm,adaptive in [('A',False),('B',True)]:
            path=out/(f'{arm}-training-{i}.sqlite')
            with BodyLoop.start(path,fixture=case['fixture'],max_actions=len(case['actions'])) as loop:
                m=AdaptiveMemory(loop,adaptive=adaptive)
                initial=loop.observe()['checkpoint_sha256']
                results=[]
                for j,action in enumerate(case['actions']):
                    observed_states.add(digest(state(loop.observe())))
                    results.append(m.execute('train-'+str(j),action,goal='closed-loop-v02 frozen training'))
                version,model=m.verify()
                assert not set(models[arm]['buckets']) & set(model['buckets']), 'ambiguous training bucket merge'
                models[arm]['buckets'].update(deepcopy(model['buckets']))
                models[arm]['failure_streak']=max(models[arm]['failure_streak'],model['failure_streak'])
                arms[arm]={'initial':initial,'results':results,'model_version':version,
                           'model_sha256':digest(model),'remaining':loop.status()['actions_remaining']}
                sources.append({'arm':arm,'fixture':case['fixture'],'database':path.name,
                                'version':version,'model_sha256':digest(model),'origin':'verified local native ledger'})
        assert arms['A']['initial']==arms['B']['initial']
        assert arms['A']['results'][0]['error']==arms['B']['results'][0]['error']
        assert [r['receipt'] for r in arms['A']['results']]==[r['receipt'] for r in arms['B']['results']]
        assert arms['A']['remaining']==arms['B']['remaining']==0
    for model in models.values():validate_model(model)
    assert models['A']==initial_model()
    return models,sources,observed_states


def cold_run(path):
    code='''import json,sys
from examples.nasuraya_body_loop.host import BodyLoop
from examples.nasuraya_body_loop.closed_loop import FrozenClosedLoop
with BodyLoop(sys.argv[1]) as loop:
 c=FrozenClosedLoop(loop)
 for _ in range(3): c.advance()
 result=c.advance()
 print(json.dumps({'result':result,'remaining':loop.status()['actions_remaining'],'model':c.contract['model'],'body_sha':loop.observe()['checkpoint_sha256']}))
'''
    p=subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True,text=True,check=True,timeout=60)
    return json.loads(p.stdout)


def score(history,models):
    paired={arm:[errors(forecast(model,row['before'],row['chosen_action'],1),row['receipt']['self_model_after'])['mae']
                  for row in history] for arm,model in models.items()}
    return {'own_path_mae':sum(r['error']['mae'] for r in history)/len(history),
            'correct_preferences':sum(r['correct_preference'] for r in history),
            'native_vetoes':sum(r['receipt']['requested_action']!=r['receipt']['actual_action'] for r in history),
            'core_overrides':sum(r['chosen_action']!=r['receipt']['requested_action'] for r in history),
            'actual_walks':sum(r['receipt']['actual_action']=='walk' for r in history),
            'physical_invalid_outcomes':sum(not r['physical_model_valid'] for r in history),
            'empirical_envelope_exceeded':sum(r['envelope_exceeded'] for r in history),
            'unseen_contexts':sum(r['unseen'] for r in history),'paired_errors':paired}


def run_benchmark(output_dir):
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=False)
    protocol=json.loads(PROTOCOL.read_text());protocol_hash=digest(protocol)
    assert protocol['algorithm']=={'alpha':ALPHA,'delta_limit':DELTA_LIMIT,'error_floor':ERROR_FLOOR}
    assert protocol['cycles_per_arm']==3
    (out/'frozen_protocol.json').write_text(json.dumps(protocol,indent=2,sort_keys=True)+'\n')
    models,sources,training_states=train(out,protocol['training'])
    model_hashes={a:digest(m) for a,m in models.items()}
    splits={}; seen_states=set(training_states)
    for split in ('validation','test'):
        cases=[]
        for case in protocol[split]:
            body=fixture(case);initial=body.checkpoint()['sha256']
            initial_state=digest(state({'checkpoint_sha256':initial,'minimum_state':body.owner.body()['minimum_state']}))
            assert initial_state not in seen_states,'initial-state split overlap'
            seen_states.add(initial_state)
            arms={}
            for arm in ('A','B'):
                path=out/(case['id']+'-'+arm+'.sqlite')
                with start_from(path,body) as loop:
                    controller=FrozenClosedLoop(loop,model=models[arm],sources=[s for s in sources if s['arm']==arm],scenario=case)
                    assert controller.contract['initial_sha']==initial
                    controller.advance()
                    first_checkpoint=loop.status()['self_model']['checkpoint_sha256']
                # Each arm physically resumes its own trajectory in a NEW interpreter.
                cold=cold_run(path)
                assert cold['result']['status'] in ('completed','blocked_physical_model')
                assert cold['remaining']==3-len(cold['result']['history'])
                assert cold['model']==models[arm]
                history=cold['result']['history']
                assert history[0]['receipt']['self_model_after']['checkpoint_sha256']==first_checkpoint
                with BodyLoop(path) as loop:
                    c=FrozenClosedLoop(loop)
                    before=loop.status()
                    replay=c.advance()
                    assert replay==cold['result'] and loop.status()==before
                    assert loop.status()['completed_cycles']==len(history)
                    c.identity.verify()
                arms[arm]={'history':history,'score':score(history,models),'initial_sha':initial,
                           'remaining':cold['remaining'],'status':cold['result']['status'],
                           'cold_recovery':True,'no_extra_effect_on_replay':True,'final_sha':cold['body_sha']}
            cases.append({'scenario':case,'arms':arms,'initial_equal':True,
                          'trajectories_differ':arms['A']['final_sha']!=arms['B']['final_sha']})
        pair_errors={a:[v for c in cases for arm in ('A','B') for v in c['arms'][arm]['score']['paired_errors'][a]] for a in ('A','B')}
        splits[split]={'cases':cases,
                      'paired_mae_on_both_paths':{a:sum(v)/len(v) for a,v in pair_errors.items()},
                      'actual_correct_preferences':{a:sum(c['arms'][a]['score']['correct_preferences'] for c in cases) for a in ('A','B')},
                      'actual_native_vetoes':{a:sum(c['arms'][a]['score']['native_vetoes'] for c in cases) for a in ('A','B')},
                      'actual_walks':{a:sum(c['arms'][a]['score']['actual_walks'] for c in cases) for a in ('A','B')},
                      'actual_actions_per_arm':{a:sum(len(c['arms'][a]['history']) for c in cases) for a in ('A','B')},
                      'paired_transitions':sum(len(arm['history']) for c in cases for arm in c['arms'].values()),
                      'unseen_contexts':{a:sum(c['arms'][a]['score']['unseen_contexts'] for c in cases) for a in ('A','B')}}
        for metric in ('physical_invalid_outcomes','empirical_envelope_exceeded'):
            splits[split][metric]={a:sum(c['arms'][a]['score'][metric] for c in cases) for a in ('A','B')}
    assert {a:digest(m) for a,m in models.items()}==model_hashes
    assert digest(json.loads(PROTOCOL.read_text()))==protocol_hash
    a,b=[splits['test']['paired_mae_on_both_paths'][arm] for arm in ('A','B')]
    stress_passed=all(splits['test']['physical_invalid_outcomes'][a]==0 and
                      splits['test']['empirical_envelope_exceeded'][a]==0 for a in ('A','B'))
    report={'schema':'nasuraya-independent-closed-loop-results/1','protocol_sha256':protocol_hash,
            'models':models,'sources':sources,'model_hashes':model_hashes,'splits':splits,
            'success':b<a and stress_passed,'forecast_improvement_confirmed':b<a,
            'stress_validation_passed':stress_passed,'improvement_percent':100*(a-b)/a if a else None,
            'predictor_parameters_frozen':True,'held_out_used_for_learning':False,
            'initial_state_fingerprints_disjoint':True,'all_budgets_preserved':True,
            'api_calls':0,'scope':'deterministic synthetic trajectories; perturbations withheld from prediction until action, shared schedule; own-path MAEs not a causal comparison'}
    (out/'closed_loop_report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False,sort_keys=True)+'\n')
    return report
