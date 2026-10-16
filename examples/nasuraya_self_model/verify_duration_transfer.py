"""Recheck native receipts and frozen holdout scores with body execution forbidden."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch

from .monitor import SelfModel, digest
from .duration_transfer import DurationMemory
from .run_duration_transfer import forecasts, cold, ARMS
from .evaluate import prepare_defaults
from unified_body_v2 import UnifiedBody, PersistentEmbodiment


def verify(output):
    root=Path(output); result=json.loads((root/'results.json').read_text())
    protocol=json.loads((root/'frozen-protocol.json').read_text())
    native=0; held_scores=[]
    with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('offline verification cannot act')), \
         patch.object(PersistentEmbodiment,'cycle',side_effect=AssertionError('offline verification cannot warm up owner')):
        for seed in protocol['seeds']:
            folder=root/str(seed)
            models={a:SelfModel(folder/(a+'.sqlite')) for a in ('B','C')}
            for filename in ('B.sqlite','C.sqlite','held-out.sqlite','policy-effects.sqlite'):
                m=SelfModel(folder/filename);m.verify()
                with m.connection() as db:
                    for intent, outcome in db.execute('SELECT intent,result FROM episodes'):
                        i,r=json.loads(intent),json.loads(outcome)
                        event=i['request']['event_id']
                        after=json.loads((folder/(event+'-after.json')).read_text())
                        b=UnifiedBody.restore(after['body'])
                        assert b.results[event]==after['receipt']==r['receipt']
                        assert r['receipt']['owner']['physical_model_valid']
                        native+=1
            for row in result['rows']:
                if row['seed']!=seed or row['split']!='held_out':
                    continue
                saved=json.loads((folder/(row['id']+'-prospective.json')).read_text())
                before=json.loads((folder/('held-'+row['id']+'-before.json')).read_text())
                predicted=forecasts(models['C'],models['B'],before['observation'],before['request'])
                assert saved==predicted==row['predictions']
                with SelfModel(folder/'held-out.sqlite').connection() as db:
                    (outcome,)=db.execute('SELECT result FROM episodes WHERE id=?',('held-'+row['id'],)).fetchone()
                admitted=json.loads(outcome)['admitted']
                assert row['actual']==admitted
                scores={a:(p['probability']-int(admitted))**2 for a,p in predicted.items()}
                assert scores==row['scores']
                held_scores.append(dict(row,scores=scores))
            assert not SelfModel(folder/'held-out.sqlite').verify()['counts']
            assert not SelfModel(folder/'policy-effects.sqlite').verify()['counts']
            assert json.loads((folder/'cold.json').read_text())==json.loads(json.dumps(cold(models['C'].path)))
        for split,rows in [('held_out',held_scores),('unseen_interpolation',
                [r for r in held_scores if r['id'].startswith('interpolate')])]:
            scores={a:sum(r['scores'][a] for r in rows)/len(rows) for a in ARMS}
            assert scores==result['mean_brier'][split]
        for row in result['policy_outcomes']:
            folder=root/str(row['seed']);event='policy-'+row['arm']+'-'+row['case']
            with SelfModel(folder/'policy-effects.sqlite').connection() as db:
                (i,r)=db.execute('SELECT intent,result FROM episodes WHERE id=?',(event,)).fetchone()
            i,r=json.loads(i),json.loads(r)
            assert row['requested']==i['request']['requested']
            assert row['actual']==r['receipt']['owner']['selected_action']
            assert row['valid']==r['receipt']['owner']['physical_model_valid']
            assert row['walk_admitted']==(row['requested']=='walk' and r['admitted'])
            assert row['restricted_walk']==(row['requested']=='walk' and bool(i['before']['audit']['walking_restrictions']))
            assert row['sleep_pressure_reduction']==i['before']['minimum']['sleep_pressure']-r['after']['minimum']['sleep_pressure']
    return dict(verified_native_receipts=native,held_out_predictions_equal=True,
                held_out_metrics_equal=True,policy_effects_equal=True,cold_equal=True,
                native_actions_executed=0,api_calls=0)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    prepare_defaults();print(json.dumps(verify(a.output),indent=2))
