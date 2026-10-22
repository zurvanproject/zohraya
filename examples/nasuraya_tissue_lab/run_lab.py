"""Run scenarios or observe a read-only native SQLite checkpoint.

    python run_lab.py --database PATH --output DIRECTORY
    python -m unittest discover -s . -v

Database access uses SQLite mode=ro and never constructs a BodyLoop host.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
from tissue_lab import TissueObserver, adapter, forecast, canonical


def execute(database, output):
    source=Path(database).resolve(); out=Path(output); out.mkdir(parents=True,exist_ok=True)
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as db:
        envelope=json.loads(db.execute('SELECT value FROM runtime WHERE key=?',('nasuraya-body-loop',)).fetchone()[0])
    q=envelope['payload']['modules']['outputs']['cardiorespiratory']['Q_L_min']
    observed=adapter(envelope,reference_flow_L_min=q)
    observer=TissueObserver(); receipt=observer.advance(observed)
    restored=TissueObserver.restore(json.loads(canonical(observer.checkpoint())))
    assert restored.checkpoint()==observer.checkpoint()
    def blockage(x): x['patency']['resonan_L']=0.
    def half_flow(x): x['Q_L_min']*=.5
    def inflammation(x): x['systemic_inflammation']=1.
    def failed_lymph(x): inflammation(x);x['lymph']['spandar']=0.
    def no_special(x):x['paid_W']['special']=0.
    cases={};traces={}
    for name,intervention in [('baseline',None),('left_resonan_blocked',blockage),('half_flow',half_flow),
        ('inflammation_intact_lymph',inflammation),('inflammation_blocked_lymph',failed_lymph),('no_special_budget',no_special)]:
        model,rows=forecast(observed,seconds=180,intervention=intervention)
        cases[name]=rows[-1];traces[name]=rows
        assert all(abs(r['flow_residual_L_min'])<1e-9 for r in rows)
        assert all(v>=-1e-12 for r in rows for v in r['paid_residual_J'].values())
    after=hashlib.sha256(source.read_bytes()).hexdigest();assert before==after
    result=dict(source_checkpoint_sha256=envelope['sha256'],source_revision=envelope['payload']['revision'],
        source_tick=observed['source_tick'],source_database_sha256=before,database_unchanged=before==after,
        recorded_receipt=receipt,forecast_seconds=180,forecast_cases=cases,
        reference_flow_L_min=q,reference_scope='normalization to this recorded software snapshot, NOT calibrated physiology',
        limitations=['read-only observer; no native actuation','indices, not cells or clinical parameters',
                    'fixed flow weights; no pressure/volume solver','no tissue repair or new native energy expenditure'])
    (out/'evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (out/'forecast_traces.json').write_text(json.dumps(traces,ensure_ascii=False)+'\n')
    (out/'observer_checkpoint.json').write_text(json.dumps(observer.checkpoint(),ensure_ascii=False,indent=2)+'\n')
    return result


if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--database',required=True);a.add_argument('--output',required=True)
    args=a.parse_args();r=execute(args.database,args.output)
    print(json.dumps({k:r[k] for k in ('source_revision','source_tick','database_unchanged','reference_flow_L_min')},indent=2))
