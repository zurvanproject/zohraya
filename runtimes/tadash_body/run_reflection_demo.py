"""Source correction, actual software body feedback, and restart demonstrations.

Initial sleep pressure is a declared test intervention recorded through the
existing owner journal. Execution uses generated fixtures, never a user state.
"""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from reflection_cycle import ReflectionCycle,ReflectiveBody
from synthetic_fixture import prepare_defaults,synthetic_body
from unified_body_v2 import UnifiedBody,PersistentEmbodiment
from memory_body_loop_v08 import MemoryBodyLoop
from renal_coupling_v09 import RenalMemoryLoop

ROOT=Path(__file__).resolve().parent

def request_template():
    cases=json.loads((ROOT/'reflection_cases.json').read_text())['cases']
    return deepcopy(next(c for c in cases if c['id']=='valid_supported_action')['request'])

def sleep_fixture():
    memory=MemoryBodyLoop(context='synthetic-sleep',epoch='synthetic-v1')
    renal=RenalMemoryLoop.from_v08_checkpoint(memory.checkpoint())
    owner=PersistentEmbodiment.bootstrap(renal.checkpoint(),datetime(2026,1,1,tzinfo=timezone.utc))
    before=owner.body()
    owner.aux['sleep_pressure']=.95
    owner._record(before,owner.body(),'external_input',
        'declared synthetic sleep-pressure fixture; not a physical measurement',0.)
    owner.cycle(event_id='declared-sleep-fixture-warm-up',at_utc='2026-01-01T00:00:07+00:00',duration_s=7.,requested='observe',external={})
    body=UnifiedBody.migrate(owner.checkpoint())
    body.migration['fixture_intervention']='sleep pressure .95 with an explicit cause-bearing owner event; no user state'
    return body

def motion_request(id,at):
    r=request_template();r.update(id=id,context='synthetic-sleep-v1',topic='optional-motion',at_utc=at)
    r['actions'][0]['body_action']='walk';r['actions'][0]['expected_outcome']={'status':'completed','selected_action':'walk'}
    r['actions'][1]['body_action']='observe';r['actions'][1]['expected_outcome']={'status':'completed','selected_action':'observe'}
    return r

def body_experiment(output):
    origin=sleep_fixture().checkpoint();rows=[]
    for memory in [False,True]:
        path=output/('body_with_memory.sqlite' if memory else 'body_without_memory.sqlite')
        with ReflectionCycle(path,use_memory=memory) as e:
            adapter=ReflectiveBody(e,body=UnifiedBody.restore(origin));steps=[]
            for i in range(2):
                r=motion_request(f'body-feedback-{i}',f'2026-01-01T00:00:0{8+i}+00:00')
                o=adapter.cycle(r,at_utc=r['at_utc']);actual=o['actual_outcome']
                steps.append(dict(decision_id=o['id'],proposed_action=o['selected_action'],requested_body_action=next(c for c in r['actions'] if c['id']==o['selected_action'])['body_action'],realized_body_action=actual.get('selected_action'),matched_expected=o['feedback']['success'],recalled_feedback_ids=o['recalled_feedback_ids'],body_audit=actual.get('body_receipt',{}).get('whole_body_audit')))
            (output/('body_with_memory_records.json' if memory else 'body_without_memory_records.json')).write_text(json.dumps(e.export(),ensure_ascii=False,indent=2))
            rows.append(dict(use_memory=memory,steps=steps))
    return rows

def protocol_experience(output):
    source=(ROOT/'reflection_protocol_source.txt').read_text()
    witness=dict(id='manual-correction',kind='observed',source_ref='library://libfile_ef6accb410448191add7a790b056493a',locator='اعمال بر سه مورد واقعی / A053L',source_sha256=sha256(source.encode()).hexdigest(),claim=dict(key='correction',value='familiar full protection phrase was unsupported; source fragment retained'))
    r=request_template();r.update(id='historical-reading-error',context='72div/8d33bb17e16dd87e562558bd5edbe56626501a0eb23a5a4680df7f7b26021828',topic='A053L/accept-without-visual-check',at_utc='2026-10-12T12:36:49+00:00')
    r['evidence']=[];r['actions'][0]['requires_evidence']=[];r['actions'][0]['claims']=[];r['actions'][0]['id']='accept_without_visual_check';r['actions'][0]['expected_outcome']={'status':'supported_reading'}
    db=output/'project_experience.sqlite'
    with ReflectionCycle(db) as e:
        e.decide(r);e.complete(r['id'],{'status':'unsupported_completion'},verified=True,evidence=[witness],reason='retrospective correction documented in retrieved protocol, not a new manuscript reading')
        e.set_commitment('72div:word_target',target=50000,actual=5042,source_ref=witness['source_ref'],locator='کار باز کتاب / coarse whitespace count')
        e.set_commitment('72div:full_collation',target=1,actual=0,source_ref=witness['source_ref'],locator='کار باز کتاب / full word-by-word collation')
        e.set_commitment('72div:verified_entry_index',target=1,actual=0,source_ref=witness['source_ref'],locator='کار باز کتاب / names and entries')
        e.set_commitment('72div:grid_checks',target=1,actual=0,source_ref=witness['source_ref'],locator='کار باز کتاب / numerical figures')
        r['id']='next-reading-strategy';r['at_utc']='2026-10-12T14:00:00+00:00';d=e.decide(r)
        export=e.export();e.backup(output/'resume_checkpoint.sqlite')
    request_path=output/'cold_request.json';r['id']='cold-reading-strategy';request_path.write_text(json.dumps(r,ensure_ascii=False,indent=2))
    cold=subprocess.run([sys.executable,str(ROOT/'reflection_cli.py'),'--db',str(output/'resume_checkpoint.sqlite'),'decide','--request',str(request_path)],capture_output=True,text=True,check=True)
    cold_record=json.loads(cold.stdout)
    if d['selected_action']!=cold_record['selected_action'] or d['recalled_feedback_ids']!=cold_record['recalled_feedback_ids']:raise AssertionError('cold experience recall diverged')
    (output/'project_experience_records.json').write_text(json.dumps(export,ensure_ascii=False,indent=2))
    (output/'cold_decision.json').write_text(json.dumps(cold_record,ensure_ascii=False,indent=2))
    return dict(historical_source=witness['source_ref'],history_type='retrospective source-linked correction',
        before_action='accept_without_visual_check',after_action=d['selected_action'],cold_action=cold_record['selected_action'],
        recalled_feedback_ids=cold_record['recalled_feedback_ids'],commitments=export['commitments'])

def main(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False);prepare_defaults()
    body=body_experiment(output);project=protocol_experience(output)
    no_memory,with_memory=body
    result=dict(schema='tadash-reflection-demonstration/1',fixture='declared synthetic initial state; no private user checkpoint loaded',body=body,project=project,
        previous_body_state_not_replaced=True,simulator_weights_changed=False,
        checks=dict(first_step_comparable=no_memory['steps'][0]['realized_body_action']==with_memory['steps'][0]['realized_body_action'],
            no_memory_repeats_vetoed_request=no_memory['steps'][1]['requested_body_action']=='walk' and no_memory['steps'][1]['realized_body_action']!='walk',
            feedback_changes_next_request=with_memory['steps'][1]['requested_body_action']=='observe',
            actual_next_outcome_matches=with_memory['steps'][1]['matched_expected'],
            cold_recall_equal=project['after_action']==project['cold_action']))
    (output/'demo_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False,indent=2))
    return all(result['checks'].values())

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    raise SystemExit(0 if main(a.output) else 1)
