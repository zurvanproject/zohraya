"""Recompute paired comparison from saved evidence, with no network or API calls."""
import copy
import json
from pathlib import Path
from . import paired_comparison as p, self_model_step as m, session as s

def audit(state, prior):
    assert state['schema']==p.SCHEMA and state['status']=='completed'
    assert state['contract']==p.CONTRACT and state['contract_sha256']==s.digest(p.CONTRACT)
    assert state['calibration']==p.calibration(prior)
    assert len(state['rounds'])==len(state['calls'])==2
    assert len({c['response_id'] for c in state['calls']})==2
    history=copy.deepcopy(state['calibration'])
    all_rows=[]
    for round_,call in zip(state['rounds'],state['calls']):
        assert round_['status']==call['status']=='completed'
        assert len(round_['records'])==6
        assert round_['history_sha256']==s.digest(history)
        request=p.payload(round_['before'],history)
        assert call['request']==request and call['request_sha256']==s.digest(request)
        assert call['usage']==s.usage(call['provider_response'])
        assert call['response_id']==call['provider_response']['id']
        predictions=p.parse(call['provider_response'])
        assert call['predictions']==round_['api_predictions']==predictions
        assert [{k:o[k] for k in ('id','fixture','duration_s')} for o in round_['before']]==p.CASES
        for o,r in zip(round_['before'],round_['records']):
            assert o==r['observation'] and o['id']==r['id']
            local=p.baselines(o,history)
            assert round_['baseline_predictions'][o['id']]==local
            assert r['predictions']==dict(local,api=next(x for x in predictions if x['id']==o['id']))
            actual=m.minimum(r['receipt']['self_model_after'])
            assert r['receipt']['status']=='complete' and r['cold_process_reopen_verified']
            for name in p.METHODS:
                assert r['scores'][name]==p.score(r['predictions'][name],actual,r['receipt']['actual_action'])
            all_rows.append(r)
        for r in round_['records']:
            o=r['observation']
            history.append(dict(id=o['id'],fixture=o['fixture'],duration_s=o['duration_s'],observed=o['observed'],
                actual_metrics=m.minimum(r['receipt']['self_model_after']),actual_action=r['receipt']['actual_action']))
        assert round_['assessment']==p.assess([round_])
    assert state['assessment']==p.assess(state['rounds'])
    cost=sum(c['usage']['estimated_upper_micro_usd'] for c in state['calls'])
    assert cost==state['incremental_estimated_micro_usd']
    assert state['total_estimated_micro_usd']==prior['total_estimated_micro_usd']+cost
    assert state['total_reserved_micro_usd']==520000<=s.CAP
    assert state['api_numeric_benefit']==all(state['assessment']['api']['metric_mae']<state['assessment'][b]['metric_mae'] for b in p.METHODS[:2])
    return dict(status='verified_offline',assessment=state['assessment'],
        rounds=[r['assessment'] for r in state['rounds']],
        api_numeric_wins={b:sum(r['scores']['api']['metric_mae']<r['scores'][b]['metric_mae'] for r in all_rows) for b in p.METHODS[:2]},
        incremental_estimated_micro_usd=cost,total_estimated_micro_usd=state['total_estimated_micro_usd'],
        input_tokens=sum(c['usage']['input_tokens'] for c in state['calls']),
        output_tokens=sum(c['usage']['output_tokens'] for c in state['calls']),
        receipt_rows=[dict(round=i+1,id=r['id'],actual_action=r['receipt']['actual_action'],scores=r['scores'])
                      for i,round_ in enumerate(state['rounds']) for r in round_['records']])

if __name__=='__main__':
    root=Path(__file__).parent/'results'
    print(json.dumps(audit(json.loads((root/'paired-comparison.json').read_text()),
                           json.loads((root/'self-model-step.json').read_text())),ensure_ascii=False,indent=2))
