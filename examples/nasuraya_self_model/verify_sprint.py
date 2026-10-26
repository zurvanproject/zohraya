"""Verify retained synthetic receipt journals offline, without executing a cycle."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import zipfile

from .embodied_learning import LearningJournal
from .monitor import digest
from .run_sprint import metrics
from unified_body_v2 import UnifiedBody


def verify(evidence, receipts):
    evidence=Path(evidence);result=json.loads((evidence/'results.json').read_text())
    manifest=json.loads((evidence/'receipt-manifest.json').read_text())
    recomputed=[]
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(receipts) as z:
        assert set(z.namelist())==set(manifest)
        for name,expected in manifest.items():
            assert Path(name).name==name and hashlib.sha256(z.read(name)).hexdigest()==expected
            (Path(tmp)/name).write_bytes(z.read(name))
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('verification must not execute native actions')):
            for row in result['rows']:
                j=LearningJournal(Path(tmp)/(row['id']+'.sqlite'));s=j.load();r=s.records[-1];d=r['decision'];receipt=r['receipt']
                saved=json.loads((Path(tmp)/(row['id']+'-prediction.json')).read_text())
                assert saved==d
                matched=receipt['owner']['selected_action']==d['request']['requested'] and receipt['owner']['physical_model_valid']
                prob=d['action_prediction']['probability']
                actual=dict(row,requested=d['request']['requested'],actual=receipt['owner']['selected_action'],
                    selected_reason=d['selected']['reason'],probability=prob,brier=(prob-int(matched))**2,
                    requested_action_admitted=matched,physical_valid=receipt['owner']['physical_model_valid'],
                    walk_admitted=d['request']['requested']=='walk' and matched,
                    recovery_gain={k:d['observation']['minimum'][k]-r['after']['minimum'][k] for k in ('sleep_pressure','fatigue','pain')},
                    native_prediction_error=receipt['owner']['prediction']['mean_scaled_absolute_error'],
                    receipt_sha256=digest(receipt),initial_body_sha256=s.contract['initial_body']['sha256'],
                    final_body_sha256=s.body.checkpoint()['sha256'])
                assert actual==row
                if row['split']=='held_out':assert s.contract['arm']!='C'
                with j.owner() as db:
                    before=db.execute('SELECT before_sha FROM receipts WHERE event_id=?',(receipt['event_id'],)).fetchone()[0]
                assert j.step(event_id=receipt['event_id'],expected_head=before)==receipt
                recomputed.append(actual)
    rebuilt={split:{a:metrics([r for r in recomputed if r['split']==split and r['arm']==a])
                    for a in 'ABC'} for split in ('adaptation','held_out')}
    assert rebuilt==result['metrics']
    return dict(verified_journals=len(recomputed),prospective_predictions_equal=True,
                metrics_equal=True,native_actions_executed=0,network_calls=0)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--evidence',required=True);p.add_argument('--receipts',required=True)
    a=p.parse_args();print(json.dumps(verify(a.evidence,a.receipts),indent=2))
