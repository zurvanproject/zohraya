"""Frozen shadow forecasts plus verified paired native training; no held-out learning."""
from pathlib import Path
import json
import subprocess
import sys
from unittest.mock import patch

from .host import BodyLoop
from .adaptive_memory import (AdaptiveMemory, FIELDS, errors, forecast, state, choose_action,
                              ALPHA, DELTA_LIMIT, ERROR_FLOOR)
from .self_maintenance import digest, plan
from synthetic_fixture import synthetic_origin
from unified_body_v2 import PersistentEmbodiment, UnifiedBody

PROTOCOL = Path(__file__).with_name('predictive_protocol.json')


def evaluation_fixture(pressure):
    """New declared test state, journaled before whole-body migration."""
    owner = PersistentEmbodiment.restore(synthetic_origin())
    before = owner.body()
    owner.aux['sleep_pressure'] = pressure
    owner._record(before, owner.body(), 'external_input',
                  'held-out synthetic sleep-pressure intervention, not a biological measurement', 0.)
    body = UnifiedBody.migrate(owner.checkpoint())
    body.migration['fixture_intervention'] = {'sleep_pressure':pressure,'source':'predictive_protocol.json'}
    return body


def sample_key(snapshot, action):
    return digest({'state':state(snapshot), 'action':action})


def run_benchmark(output_dir):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(PROTOCOL.read_text())
    assert protocol['frozen_algorithm'] == {'alpha':ALPHA,'delta_limit':DELTA_LIMIT,'error_floor':ERROR_FLOOR}
    frozen_hash = digest(protocol)
    training, models, seen = [], {}, {'training':set(), 'validation':set(), 'test':set()}
    # The training function sees only the training split, never validation/test results.
    for i, case in enumerate(protocol['training']):
        arm_records = {}
        for arm, adaptive in [('A',False),('B',True)]:
            path = out / (arm + '-train-' + str(i) + '.sqlite')
            with BodyLoop.start(path,fixture=case['fixture'],max_actions=len(case['actions'])) as loop:
                memory = AdaptiveMemory(loop,adaptive=adaptive)
                # Each context gets its own independent learned parameters.
                initial = loop.observe()['checkpoint_sha256']
                steps = [memory.execute('train-'+str(j),a,goal='frozen training contract') for j,a in enumerate(case['actions'])]
                for raw, in loop.engine.db.execute('SELECT intent FROM nasu_experiences'):
                    intent = json.loads(raw)
                    seen['training'].add(sample_key(intent['before'],intent['action']))
                version, model = memory.verify()
                arm_records[arm] = {'initial':initial,'steps':steps,'remaining':loop.status()['actions_remaining'],
                                    'version':version, 'model':model, 'database':path.name}
                models[(arm,case['fixture'])] = (version, model)
        a,b = arm_records['A'], arm_records['B']
        assert a['initial'] == b['initial']
        assert a['remaining'] == b['remaining'] == 0
        assert [x['receipt'] for x in a['steps']] == [x['receipt'] for x in b['steps']]
        training.append({'case':case,'arms':arm_records})
    # New interpreter recovers the full learned model and confirms fixed budgets.
    recovery = []
    for i, case in enumerate(protocol['training']):
        for arm, adaptive in [('A',False),('B',True)]:
            path = out/(arm+'-train-'+str(i)+'.sqlite')
            code = '''import json,sys
from examples.nasuraya_body_loop.host import BodyLoop
from examples.nasuraya_body_loop.adaptive_memory import AdaptiveMemory
with BodyLoop(sys.argv[1]) as loop:
 m=AdaptiveMemory(loop,adaptive=sys.argv[2]=='True')
 m.reconcile()
 print(json.dumps({'version_model':m.verify(),'remaining':loop.status()['actions_remaining'],'cycles':loop.status()['completed_cycles']}))
'''
            proc = subprocess.run([sys.executable,'-c',code,str(path),str(adaptive)],capture_output=True,text=True,check=True,timeout=60)
            cold = json.loads(proc.stdout)
            assert cold['version_model'] == list(models[(arm,case['fixture'])])
            assert cold['remaining'] == 0 and cold['cycles'] == len(case['actions'])
            recovery.append({'arm':arm,'fixture':case['fixture'],'parameters_equal':True,'remaining':0,'cycles':cold['cycles']})
    evaluation = {}
    model_hash_before = digest({str(k):v for k,v in models.items()})
    for split in ('validation','test'):
        rows = []
        for i, case in enumerate(protocol[split]):
            path = out/(split+'-'+str(i)+'.sqlite')
            factory_name = 'synthetic_body' if case['fixture']=='normal' else 'sleep_fixture'
            with patch('examples.nasuraya_body_loop.host.'+factory_name,
                       side_effect=lambda: evaluation_fixture(case['initial_sleep_pressure'])):
                created = BodyLoop.start(path,fixture=case['fixture'],max_actions=case['warmup']+1)
            with created as loop:
                for j in range(case['warmup']):
                    loop.observe()
                    loop.step(decision_id='warm-'+str(j),preferred_action='observe',duration_s=.1)
                before = loop.observe()
                fingerprint = sample_key(before,case['action'])
                assert fingerprint not in seen['training'], 'held-out training overlap'
                if split=='test':
                    assert fingerprint not in seen['validation'], 'held-out validation overlap'
                seen[split].add(fingerprint)
                forecasts, choices = {}, {}
                for arm in ('A','B'):
                    version, model = models[(arm,case['fixture'])]
                    forecasts[arm] = forecast(model,before,case['action'],version)
                    choices[arm] = choose_action(model,before,version)
                outcome = loop.step(decision_id='held-out',preferred_action=case['action'],duration_s=.1)
                assert outcome['status']=='complete'
                # Scoring only: no AdaptiveMemory in the held-out native session.
                row = {'case':case,'before':before,'outcome':outcome,'forecasts':forecasts,
                       'error':{a:errors(p,outcome['self_model_after']) for a,p in forecasts.items()},
                       'decision_contract':plan(before)['requested_action'],'recommendations':choices,
                       'remaining':loop.status()['actions_remaining']}
                rows.append(row)
        evaluation[split] = {'cases':rows,
             'mae':{a:sum(r['error'][a]['mae'] for r in rows)/len(rows) for a in ('A','B')},
             'mae_by_field':{a:{f:sum(r['error'][a]['absolute'][f] for r in rows)/len(rows) for f in FIELDS} for a in ('A','B')},
             'correct_decisions':{a:sum(r['recommendations'][a]==r['decision_contract'] for r in rows) for a in ('A','B')},
             'native_vetoes':sum(r['outcome']['requested_action'] != r['outcome']['actual_action'] for r in rows),
             'all_budgets_preserved':all(r['remaining']==0 for r in rows)}
    assert digest({str(k):v for k,v in models.items()}) == model_hash_before
    assert digest(json.loads(PROTOCOL.read_text())) == frozen_hash
    a,b = evaluation['test']['mae']['A'], evaluation['test']['mae']['B']
    report = {'schema':'nasuraya-predictive-benchmark/1','protocol_sha256':frozen_hash,
              'training':training,'evaluation':evaluation,'cold_recovery':recovery,
              'test_used_for_training':False,'held_out_parameters_unchanged':True,
              'input_action_fingerprints_disjoint':True,
              'improvement_percent':100*(a-b)/a if a else None,
              'success':b<a and all(x['all_budgets_preserved'] for x in evaluation.values()),
              'api_calls':0,'scope':'12 paired training transitions; 3 validation and 6 held-out synthetic transitions; no biological/general intelligence claim'}
    (out/'predictive_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
    return report
