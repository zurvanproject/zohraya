"""Reproducible native-receipt A/B/C trial; no live API required."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys

from .monitor import SelfModel, snapshot, digest, ROOT
from .evaluate import fixture, request, prepare_defaults
from .embodied_learning import LearningSession, LearningJournal
from persistent_embodiment_v1 import atomic_json


def train(path, protocol):
    model=SelfModel.create(path)
    for i,p in enumerate(protocol['training_pressures']):
        b=fixture(p);q=request(b,'train-'+str(i),protocol['training_duration_s']);q['external']={}
        model.begin(b,q);r=b.cycle(**q);model.finish(q['event_id'],b,r)
    return model


def one(out, body, seed_model, *, ident, arm, duration, practice):
    session=LearningSession.start(body,seed_model,session_id=ident,arm=arm,
        max_ticks=1,practice_ticks=int(practice),duration_s=duration)
    journal=LearningJournal.create(out/(ident+'.sqlite'),session)
    before=session.checkpoint();d=session.decision()
    atomic_json(out/(ident+'-prediction.json'),d)  # committed before body execution
    q=session.request();r=journal.step(event_id=q['event_id'],expected_head=before['sha256'])
    after=journal.load();row=after.records[-1]
    matched=r['owner']['selected_action']==q['requested'] and r['owner']['physical_model_valid']
    prob=d['action_prediction']['probability']
    return after,dict(id=ident,arm=arm,requested=q['requested'],actual=r['owner']['selected_action'],
        selected_reason=d['selected']['reason'],probability=prob,brier=(prob-int(matched))**2,
        requested_action_admitted=matched,physical_valid=r['owner']['physical_model_valid'],
        walk_admitted=q['requested']=='walk' and matched,
        recovery_gain={k:row['decision']['observation']['minimum'][k]-row['after']['minimum'][k]
                       for k in ('sleep_pressure','fatigue','pain')},
        native_prediction_error=r['owner']['prediction']['mean_scaled_absolute_error'],
        receipt_sha256=digest(r),initial_body_sha256=before['payload']['body']['sha256'],
        final_body_sha256=after.body.checkpoint()['sha256'])


def metrics(rows):
    n=len(rows)
    return dict(n=n,mean_brier=sum(r['brier'] for r in rows)/n,
        walk_admissions=sum(r['walk_admitted'] for r in rows),
        requested_action_admissions=sum(r['requested_action_admitted'] for r in rows),
        native_protective_substitutions=sum(r['requested']!=r['actual'] for r in rows),
        invalid_physical_outcomes=sum(not r['physical_valid'] for r in rows),
        mean_native_prediction_error=sum(r['native_prediction_error'] for r in rows)/n,
        sleep_pressure_reduction=sum(r['recovery_gain']['sleep_pressure'] for r in rows))


def evaluate(output):
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    protocol_file=Path(__file__).with_name('sprint_protocol.json')
    protocol=json.loads(protocol_file.read_text());atomic_json(out/'frozen-protocol.json',protocol)
    prepare_defaults();model=train(out/'training.sqlite',protocol)
    original=hashlib.sha256(model.path.read_bytes()).hexdigest()
    rows=[];cold_checks=[]
    for seed in protocol['seeds']:
        rng=random.Random(seed);last={arm:model for arm in ('A','B','C')}
        for i in range(protocol['adaptation_trials_per_seed']):
            pressure=rng.uniform(*protocol['adaptation_pressure_range'])
            paired=[]
            for arm in ('A','B','C'):
                # Independent new native object and durable journal per arm/trial.
                parent=last['C'] if arm=='C' else model
                s,r=one(out,fixture(pressure),parent,ident=f's{seed}-{arm}-{i}',arm=arm,
                    duration=protocol['adaptation_duration_s'],practice=i<protocol['authorized_practice_trials'])
                last[arm]=s;r.update(seed=seed,trial=i,split='adaptation');rows.append(r);paired.append(r)
            assert len({r['initial_body_sha256'] for r in paired})==1
        # Held-out probes use frozen learning and common requests; they never feed adaptation.
        frozen=deepcopy(last['C'].knowledge())
        for case in protocol['held_out']:
            for arm in ('A','B','C'):
                parent=last['C'] if arm=='C' else model
                held_arm='A' if arm=='A' else 'B'
                s,r=one(out,fixture(case['sleep_pressure']),parent,
                    ident=f's{seed}-{arm}-held-{case["id"]}',arm=held_arm,
                    duration=case['duration_s'],practice=True)
                assert digest(s.knowledge())==digest(parent.knowledge() if isinstance(parent,LearningSession) else parent.verify())
                r.update(arm=arm,seed=seed,case=case['id'],split='held_out');rows.append(r)
        assert last['C'].knowledge()==frozen
        # Fresh-process inspect and completed receipt replay do no native work.
        journal=out/f's{seed}-C-{protocol["adaptation_trials_per_seed"]-1}.sqlite'
        cold=out/f'cold-{seed}.json'
        subprocess.run([sys.executable,'-m','examples.nasuraya_self_model.run_sprint','cold','--journal',str(journal),'--output',str(cold)],cwd=ROOT,check=True)
        expected=dict(checkpoint_sha256=last['C'].checkpoint()['sha256'],knowledge=last['C'].knowledge())
        assert json.loads(cold.read_text())==json.loads(json.dumps(expected));cold_checks.append(True)
    result=dict(protocol_sha256=hashlib.sha256(protocol_file.read_bytes()).hexdigest(),
        rows=rows,metrics={split:{a:metrics([r for r in rows if r['split']==split and r['arm']==a])
                                 for a in ('A','B','C')} for split in ('adaptation','held_out')},
        cold_restores_equal=all(cold_checks),held_out_updates=0,
        original_training_unchanged=hashlib.sha256(model.path.read_bytes()).hexdigest()==original,
        api_calls=0,official_state_advanced=False,
        limitations=['Three seed clusters share one deterministic software body; no inferential p-value.',
          'A is a fixed walk-request baseline, B is a conservative frozen evidence gate.',
          'Adaptation Brier mixes action choices; held-out common probes isolate prediction comparison.',
          'Admission of a short walk does not demonstrate a completed landing, smoother gait or general intelligence.',
          'Learning is context-count updating, not language-model weight training.',
          'Full recovery and previously unseen context transfer are not established.'])
    assert result['original_training_unchanged']
    atomic_json(out/'results.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))


def cold(journal,output):
    from unittest.mock import patch
    from unified_body_v2 import UnifiedBody
    with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('cold replay must not execute')):
        j=LearningJournal(journal);s=j.load();r=s.records[-1]
        # Recover the prior head from the durable receipt, then deduplicate the exact event.
        with j.owner() as db:
            head=db.execute('SELECT before_sha FROM receipts WHERE event_id=?',(r['receipt']['event_id'],)).fetchone()[0]
        assert j.step(event_id=r['receipt']['event_id'],expected_head=head)==r['receipt']
        atomic_json(output,dict(checkpoint_sha256=s.checkpoint()['sha256'],knowledge=s.knowledge()))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('evaluate','cold'))
    p.add_argument('--output',required=True);p.add_argument('--journal');a=p.parse_args()
    if a.mode=='evaluate':evaluate(a.output)
    else:cold(a.journal,a.output)
