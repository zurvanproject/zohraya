"""Real process exits and 10,000-row capacity test on isolated generated stores."""
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
import argparse, hashlib, json, os, shutil, sqlite3, subprocess, sys, time
from reflection_cycle import ReflectionCycle, InterruptedExecution, MAX_DECISIONS, canonical, digest
ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--old-root',type=Path,required=True);p.add_argument('--resume-fixture',action='store_true');a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=a.resume_fixture)
frozen=json.loads((ROOT/'stage2_cases.json').read_text());base=deepcopy(next(c for c in frozen['cases'] if c['type']=='related' and c['split']=='final'));r=base['history'][0]['request'];w=base['history'][0]['evidence'];results=[]
def check(name,condition,**details):
 results.append(dict(name=name,passed=bool(condition),**details))
 if not condition:raise AssertionError(name)
def child(code,*args,root=ROOT):
 return subprocess.run([sys.executable,'-c',code,*map(str,args)],cwd=root,capture_output=True,text=True)
req=out/'request.json';req.write_text(json.dumps(r));wit=out/'witness.json';wit.write_text(json.dumps(w))
start=time.perf_counter()
with ReflectionCycle(out/'capacity.sqlite') as e:
 e.set_commitment('72div:words',target=50000,actual=5042,source_ref='library://source-package',locator='Reading_Edition.txt')
 e.decide(r);e.complete(r['id'],{'status':'failed'},verified=True,evidence=w,reason='observed synthetic failure')
 filler=deepcopy(r);filler['actions'][0]['id']='irrelevant_success'
 # Bulk fixture rows are explicitly constructed from one engine-completed
 # representative. This is a capacity/retrieval test, not 10,000 executions.
 existing=e.db.execute('SELECT count(*) FROM decisions').fetchone()[0]
 sample=deepcopy(filler);sample['id']='capacity-1'
 template=e.get(sample['id'])
 if template is None:
  e.decide(sample);template=e.complete(sample['id'],{'status':'completed'},verified=True,evidence=w,reason='generated capacity control');existing+=1
 tail=e.db.execute("SELECT record FROM decisions WHERE status='planned'").fetchall()
 for item in tail:
  pending=json.loads(item[0]);e.complete(pending['id'],{'status':'completed'},verified=True,evidence=w,reason='generated capacity control')
 rows=[]
 for i in range(existing,MAX_DECISIONS):
  candidate=deepcopy(template);new_request=deepcopy(sample);new_request['id']='capacity-'+str(i)
  fingerprint=digest(dict(request=new_request,engine=e.engine_fingerprint,use_memory=True))
  candidate.update(id=new_request['id'],sequence=i+1,request=new_request,request_fingerprint=fingerprint)
  rows.append((candidate['id'],i+1,fingerprint,candidate['context'],candidate['topic'],'complete',canonical(candidate)))
 with e.transaction():
  e.db.executemany('INSERT INTO decisions VALUES(?,?,?,?,?,?,?)',rows)
  for item in rows:e._index_feedback(json.loads(item[-1]))
 probe=deepcopy(base['request']);probe['id']='capacity-excess'
 count=e.db.execute('SELECT count(*) FROM decisions').fetchone()[0]
 try:e.decide(probe);raised=False
 except ValueError as ex:raised='capacity' in str(ex)
 check('capacity_refuses_without_deleting',raised and count==10000 and e.db.execute('SELECT count(*) FROM decisions').fetchone()[0]==10000)
 memories=e.recall(probe['context'],probe['topic'],at_utc=probe['at_utc']);check('earliest_correction_recalled_at_capacity',any(v['decision_id']==r['id'] and not v['success'] for v in memories.values()))
 e.backup(out/'capacity_backup.sqlite');check('integrity_at_capacity',e.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
with ReflectionCycle(out/'capacity_backup.sqlite') as b:
 check('backup_preserves_all_decisions_and_commitment',b.db.execute('SELECT count(*) FROM decisions').fetchone()[0]==10000 and b.commitments()[0]['remaining']==44958)
check('cold_capacity_recovery',child("from reflection_cycle import ReflectionCycle;import sys;e=ReflectionCycle(sys.argv[1]);assert e.db.execute('select count(*) from decisions').fetchone()[0]==10000;assert e.commitments()[0]['target']==50000;e.close()",out/'capacity_backup.sqlite').returncode==0)
for mode in ['before_plan_commit','during_completion','after_complete']:
 db=out/(mode+'.sqlite');effect=out/(mode+'.effect')
 with ReflectionCycle(db) as e:e.attach_runtime('test-state',{'revision':0})
 code="""
import json,os,sys
from pathlib import Path
from reflection_cycle import ReflectionCycle,digest
db,req,wit,mode,effect=sys.argv[1:];r=json.loads(Path(req).read_text());w=json.loads(Path(wit).read_text());e=ReflectionCycle(db)
e.db.create_function('terminate_now',0,lambda:os._exit(23))
if mode=='before_plan_commit':
 e.db.execute("CREATE TEMP TRIGGER stop_plan AFTER INSERT ON decisions BEGIN SELECT terminate_now(); END")
 e.decide(r)
else:
 if mode=='during_completion':e.db.execute("CREATE TEMP TRIGGER stop_complete AFTER UPDATE ON decisions WHEN NEW.status='complete' BEGIN SELECT terminate_now(); END")
 def callback(candidate):Path(effect).write_text('one observable effect');return {'status':'completed'}
 e.execute(r,callback,verified=True,evidence=w,reason='fixture effect',runtime_hook=lambda actual:('test-state',digest({'revision':0}),{'revision':1}))
 os._exit(23)
"""
 process=child(code,db,req,wit,mode,effect);check(mode+'_real_process_exit',process.returncode==23)
 with ReflectionCycle(db) as e:
  d=e.get(r['id']);state=e.runtime('test-state')
  if mode=='before_plan_commit':check('plan_transaction_rolls_back',d is None and not effect.exists() and state=={'revision':0})
  elif mode=='during_completion':
   check('feedback_and_runtime_rollback_together',d['status']=='running' and state=={'revision':0} and effect.read_text()=='one observable effect')
   calls=[]
   try:e.execute(r,lambda c:calls.append(c));blocked=False
   except InterruptedExecution:blocked=True
   check('interrupted_effect_never_automatically_replayed',blocked and calls==[])
   resolved=e.complete(r['id'],{'status':'completed'},verified=True,evidence=w,reason='explicit examination of effect file')
   check('explicit_reconciliation_completes',resolved['status']=='complete')
  else:
   calls=[];replay=e.execute(r,lambda c:calls.append(c));check('completed_receipt_replays_without_effect',calls==[] and replay['status']=='complete' and state=={'revision':1})
  check(mode+'_integrity',e.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
# Old-version ledger is generated by the recovered engine in another process.
old=out/'old_version.sqlite'
code="from pathlib import Path;import json,sys;from reflection_cycle import ReflectionCycle;r=json.loads(Path(sys.argv[2]).read_text());w=json.loads(Path(sys.argv[3]).read_text());e=ReflectionCycle(sys.argv[1]);e.execute(r,lambda c:{'status':'failed'},verified=True,evidence=w,reason='old version receipt');e.backup(sys.argv[4]);e.close()"
check('old_version_fixture_created',child(code,old,req,wit,out/'old_untouched.sqlite',root=a.old_root.resolve()).returncode==0)
original=sqlite3.connect(out/'old_untouched.sqlite');old_record=original.execute('SELECT record FROM decisions').fetchone()[0];original.close()
with ReflectionCycle(old) as e:
 check('index_upgrade_keeps_original_record',e.db.execute('SELECT record FROM decisions').fetchone()[0]==old_record)
 check('old_receipt_replay_survives_upgrade',e.execute(r,lambda c:(_ for _ in ()).throw(AssertionError('must not run')))['status']=='complete')
 probe=deepcopy(base['request']);probe['id']='upgrade-probe';check('old_feedback_recovered_with_new_signature',e.decide(probe)['selected_action']==base['expected'])
summary=dict(schema='tadash-stage2-durability/1',checks=results,passed=sum(x['passed'] for x in results),count=len(results),elapsed_s=time.perf_counter()-start,capacity_rows=10000,database_bytes=(out/'capacity_backup.sqlite').stat().st_size,scope='Isolated fixtures; capacity fixture bulk seeded from an engine-completed template, not 10,000 end-to-end executions. Crash tests use unmodified native per-decision FULL transactions. Real subprocess exits; sequential execution; no private memory loaded or modified')
(out/'results.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
