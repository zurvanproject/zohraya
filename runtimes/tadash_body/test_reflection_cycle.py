from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from reflection_cycle import ReflectionCycle, ReflectiveBody, InterruptedExecution

ROOT=Path(__file__).resolve().parent
CASES=json.loads((ROOT/'reflection_cases.json').read_text())['cases']
def case(name='related_correction'):return deepcopy(next(c for c in CASES if c['id']==name))
def teach(e,c=None,verified=True):
 t=(c or case())['training'];e.decide(t['request'])
 return e.complete(t['request']['id'],t['actual_outcome'],verified=verified,evidence=t['feedback_evidence'],reason='verified frozen training fixture')

class ReflectionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.dir=Path(self.tmp.name);self.engine=ReflectionCycle(self.dir/'ledger.sqlite')
 def tearDown(self):self.engine.close();self.tmp.cleanup()
 def test_frozen_contract_cases(self):
  for c in CASES:
   with self.subTest(case=c['id']),ReflectionCycle(self.dir/(c['id']+'.sqlite')) as e:
    if c['training']:teach(e,c)
    self.assertEqual(e.decide(c['request'])['selected_action'],c['expected'])
 def test_new_process_recalls_feedback_and_commitment(self):
  c=case();t=teach(self.engine)
  self.engine.set_commitment('72div:words',target=50000,actual=5042,source_ref='library://reflection-protocol',locator='unfinished-book')
  before=self.engine.decide(c['request']);probe=deepcopy(c['request']);probe['id']='restart-probe'
  req=self.dir/'request.json';req.write_text(json.dumps(probe));self.engine.close()
  result=subprocess.run([sys.executable,str(ROOT/'reflection_cli.py'),'--db',str(self.dir/'ledger.sqlite'),'decide','--request',str(req)],capture_output=True,text=True,check=True)
  after=json.loads(result.stdout)
  self.assertEqual(before['selected_action'],after['selected_action']);self.assertEqual(before['recalled_feedback_ids'],after['recalled_feedback_ids'])
  self.engine=ReflectionCycle(self.dir/'ledger.sqlite');self.assertEqual(self.engine.get(t['id'])['actual_outcome'],t['actual_outcome']);self.assertEqual(self.engine.commitments()[0]['remaining'],44958)
 def test_identical_execution_replay_is_not_reexecuted(self):
  r=case('valid_supported_action')['request'];calls=[]
  def executor(c):calls.append(c['id']);return {'status':'completed'}
  first=self.engine.execute(r,executor);second=self.engine.execute(r,executor)
  self.assertEqual(calls,['act']);self.assertEqual(first,second)
 def test_two_connections_share_execution_receipt(self):
  r=case('valid_supported_action')['request'];calls=[];self.engine.decide(r)
  with ReflectionCycle(self.dir/'ledger.sqlite') as peer:peer.execute(r,lambda c:(calls.append(c['id']) or {'status':'completed'}))
  self.engine.execute(r,lambda c:(calls.append(c['id']) or {'status':'completed'}));self.assertEqual(calls,['act'])
 def test_interruption_requires_explicit_outcome_resolution(self):
  r=case('valid_supported_action')['request'];calls=[]
  def interrupted(c):calls.append(c['id']);raise KeyboardInterrupt()
  with self.assertRaises(KeyboardInterrupt):self.engine.execute(r,interrupted)
  self.engine.close();self.engine=ReflectionCycle(self.dir/'ledger.sqlite')
  with self.assertRaises(InterruptedExecution):self.engine.execute(r,interrupted)
  self.assertEqual(calls,['act']);out=self.engine.complete(r['id'],{'status':'completed'},verified=False,evidence=[],reason='explicit outcome reconciliation');self.assertEqual(out['status'],'complete')
 def test_conflicting_request_does_not_change_ledger(self):
  r=case('valid_supported_action')['request'];self.engine.decide(r);before=self.engine.export();r['goal']='different request'
  with self.assertRaises(ValueError):self.engine.decide(r)
  self.assertEqual(before,self.engine.export())
 def test_conflicting_feedback_does_not_change_ledger(self):
  t=teach(self.engine);before=self.engine.export()
  with self.assertRaises(ValueError):self.engine.complete(t['id'],{'status':'completed'},verified=True,evidence=t['feedback']['evidence'],reason='different feedback')
  self.assertEqual(before,self.engine.export())
 def test_unverified_feedback_cannot_change_preference(self):
  teach(self.engine,verified=False);self.assertEqual(self.engine.decide(case()['request'])['selected_action'],'accept_ocr')
 def test_invalid_feedback_is_rejected_before_executor_runs(self):
  r=case('valid_supported_action')['request'];calls=[]
  with self.assertRaises(ValueError):self.engine.execute(r,lambda c:calls.append(c),verified=True)
  self.assertEqual(calls,[]);self.assertEqual(self.engine.export()['decisions'],[])
 def test_verified_success_supersedes_previous_negative(self):
  c=case();teach(self.engine);r=deepcopy(c['request']);r['id']='verified-recovery';r['actions']=r['actions'][:1]
  self.engine.execute(r,lambda c:{'status':'completed'},verified=True,evidence=c['training']['feedback_evidence'],reason='fresh verification of recovered operation')
  probe=deepcopy(c['request']);probe['id']='after-success';self.assertEqual(self.engine.decide(probe)['selected_action'],'accept_ocr')
 def test_changed_action_semantics_not_penalized(self):
  c=case();teach(self.engine);r=c['request'];r['evidence']=case('valid_supported_action')['request']['evidence'];r['actions'][0]['claims']=[{'key':'reading','value':'short reading'}]
  record=self.engine.decide(r);self.assertEqual(record['selected_action'],'accept_ocr');self.assertEqual(next(x for x in record['options'] if x['action_id']=='accept_ocr')['memory_penalty'],0.)
 def test_inference_and_authored_evidence_do_not_authorize_factual_claim(self):
  for kind in ['inference','authored']:
   r=case('valid_supported_action')['request'];r['id']='provenance-'+kind;r['evidence'][0]['kind']=kind;self.assertEqual(self.engine.decide(r)['selected_action'],'inspect_source')
 def test_expired_observation_is_not_current_support(self):
  r=case('valid_supported_action')['request'];r['evidence'][0]['expires_at']='2026-10-11T00:00:00+00:00';self.assertEqual(self.engine.decide(r)['selected_action'],'inspect_source')
 def test_contradictory_observations_do_not_hide_behind_matching_one(self):
  r=case('valid_supported_action')['request'];other=deepcopy(r['evidence'][0]);other['id']='contrary';other['claim']['value']='contrary';r['evidence'].append(other);self.assertEqual(self.engine.decide(r)['selected_action'],'inspect_source')
 def test_permutation_keeps_selection(self):
  c=case();teach(self.engine);before=self.engine.decide(c['request']);r=deepcopy(c['request']);r['id']='permuted';r['actions'].reverse();r['goals'].reverse();r['evidence'].reverse();self.assertEqual(before['selected_action'],self.engine.decide(r)['selected_action'])
 def test_no_eligible_action_abstains_without_execution(self):
  r=case('incomplete_evidence')['request'];r['actions']=r['actions'][:1];calls=[];out=self.engine.execute(r,lambda c:calls.append(c));self.assertIsNone(out['selected_action']);self.assertEqual(calls,[])
 def test_caught_executor_failure_is_recorded_and_retrievable(self):
  c=case();r=c['training']['request']
  def fail(c):raise RuntimeError('fixture tool failed')
  out=self.engine.execute(r,fail,verified=True,evidence=c['training']['feedback_evidence'],reason='observed fixture callback exception');self.assertEqual(out['actual_outcome']['error_type'],'RuntimeError');self.assertFalse(out['feedback']['success']);self.assertEqual(self.engine.decide(c['request'])['selected_action'],'inspect_source')
 def test_atomic_runtime_feedback_update_rejects_stale_snapshot(self):
  r=case('valid_supported_action')['request'];self.engine.attach_runtime('body',{'revision':0});self.engine.decide(r);before=self.engine.export()
  with self.assertRaises(ValueError):self.engine.complete(r['id'],{'status':'completed'},verified=False,evidence=[],reason='stale callback',runtime_update=('body','wrong-digest',{'revision':1}))
  self.assertEqual(self.engine.runtime('body'),{'revision':0});self.assertEqual(self.engine.export(),before)
 def test_commitment_cannot_complete_early_or_change_target(self):
  row=self.engine.set_commitment('book',target=50000,actual=5042,source_ref='library://protocol',locator='book')
  with self.assertRaises(ValueError):self.engine.set_commitment('book',target=50000,actual=5042,source_ref='library://protocol',locator='book',status='completed')
  with self.assertRaises(ValueError):self.engine.set_commitment('book',target=5042,actual=5042,source_ref='library://protocol',locator='book')
  self.assertEqual(self.engine.commitments(),[row])
 def test_backup_survives_original_database_removal(self):
  teach(self.engine);backup=self.dir/'backup.sqlite';self.engine.backup(backup);expected=self.engine.export();self.engine.close();(self.dir/'ledger.sqlite').unlink()
  with ReflectionCycle(backup) as recovered:self.assertEqual(recovered.export(),expected)
  self.engine=ReflectionCycle(self.dir/'new.sqlite')
 def test_foreign_database_is_not_adopted(self):
  foreign=self.dir/'foreign.sqlite';connection=sqlite3.connect(foreign);connection.execute('CREATE TABLE other(a)');connection.commit();connection.close()
  with self.assertRaises(ValueError):ReflectionCycle(foreign)
  connection=sqlite3.connect(foreign);self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),[('other',)]);connection.close()

class BodyIntegrationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from synthetic_fixture import prepare_defaults
  prepare_defaults()
 def test_actual_body_feedback_changes_next_requested_action(self):
  from run_reflection_demo import sleep_fixture,motion_request
  from unified_body_v2 import UnifiedBody
  origin=sleep_fixture().checkpoint();outcomes={}
  for memory in [False,True]:
   with tempfile.TemporaryDirectory() as tmp,ReflectionCycle(Path(tmp)/'state.sqlite',use_memory=memory) as e:
    adapter=ReflectiveBody(e,body=UnifiedBody.restore(origin));rows=[]
    for i in range(2):
     r=motion_request('repeat-'+str(i),'2026-01-01T00:00:0'+str(8+i)+'+00:00')
     rows.append(adapter.cycle(r,at_utc=r['at_utc']))
    outcomes[memory]=rows
  self.assertEqual(outcomes[False][0]['actual_outcome']['selected_action'],outcomes[True][0]['actual_outcome']['selected_action'])
  self.assertFalse(outcomes[True][0]['feedback']['success'])
  self.assertEqual(outcomes[False][1]['selected_action'],'act')
  self.assertEqual(outcomes[True][1]['selected_action'],'inspect_source')
  self.assertEqual(outcomes[True][1]['actual_outcome']['selected_action'],'observe')
  self.assertTrue(outcomes[True][1]['feedback']['success'])
 def test_existing_body_executes_and_resumes_in_new_process(self):
  from synthetic_fixture import synthetic_body
  r=case('valid_supported_action')['request'];r['id']='body-step';r['at_utc']='2026-01-01T00:00:08+00:00'
  for c in r['actions']:c['body_action']='observe';c['expected_outcome']={'status':'completed','selected_action':'observe'}
  with tempfile.TemporaryDirectory() as tmp:
   db=Path(tmp)/'body.sqlite'
   with ReflectionCycle(db) as e:
    adapter=ReflectiveBody(e,body=synthetic_body());result=adapter.cycle(r,at_utc=r['at_utc'])
    self.assertEqual(result['actual_outcome']['selected_action'],'observe');self.assertTrue(result['actual_outcome']['body_receipt']['owner']['physical_model_valid'])
    audit=result['actual_outcome']['body_receipt']['whole_body_audit'];self.assertLess(audit['energy_error_J'],5e-5);self.assertLess(audit['water_error_L'],1e-8);self.assertLess(audit['neural_clock_error_s'],1e-7)
    self.assertEqual(result,adapter.cycle(r,at_utc=r['at_utc']))
    with self.assertRaises(ValueError):adapter.cycle(r,at_utc=r['at_utc'],external={'meal_J':1.})
    planned=deepcopy(r);planned['id']='body-next';planned['at_utc']='2026-01-01T00:00:09+00:00';continuous=adapter.cycle(planned,at_utc=planned['at_utc']);next_checkpoint=continuous['actual_outcome']['body_checkpoint']
    clone=Path(tmp)/'clone.sqlite'
    with ReflectionCycle(clone) as ce:ce.attach_runtime('tadash-body',result['actual_outcome']['body_checkpoint'])
   req=Path(tmp)/'request.json';req.write_text(json.dumps(planned))
   code="import json,sys;from pathlib import Path;from reflection_cycle import ReflectionCycle,ReflectiveBody;r=json.loads(Path(sys.argv[2]).read_text());e=ReflectionCycle(sys.argv[1]);o=ReflectiveBody(e).cycle(r,at_utc=r['at_utc']);print(json.dumps(o['actual_outcome']));e.close()"
   cold=subprocess.run([sys.executable,'-c',code,str(clone),str(req)],cwd=ROOT,capture_output=True,text=True,check=True);restored=json.loads(cold.stdout)
   self.assertEqual(restored['body_checkpoint'],next_checkpoint);self.assertEqual(restored['body_receipt'],continuous['actual_outcome']['body_receipt'])

if __name__=='__main__':unittest.main()
