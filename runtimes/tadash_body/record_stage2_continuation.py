"""Resume a copied task ledger, record the actual inspected source, retain promises."""
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import argparse,hashlib,json,sqlite3,subprocess,sys
from reflection_cycle import ReflectionCycle
ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--source-ledger',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--book-output',type=Path,required=True);a=p.parse_args();a.output.mkdir(exist_ok=True,parents=True)
db=a.output/'continuation.sqlite';source_hash=hashlib.sha256(a.source_ledger.read_bytes()).hexdigest()
if db.exists():raise ValueError('new continuation destination required')
source=sqlite3.connect('file:'+str(a.source_ledger.resolve())+'?mode=ro',uri=True);target=sqlite3.connect(db);source.backup(target);target.close();source.close()
with ReflectionCycle(db) as e:
 historical=e.get('historical-reading-error');request=deepcopy(historical['request']);request['id']='stage2-A053L-source-return';request['at_utc']=datetime.now(timezone.utc).isoformat();request['goal']='Reinspect the exact previously misread A053L span and preserve unresolved surrounding text'
 witness=dict(id='A053L-new-fragment',kind='observed',source_ref='library://libfile_48db4b7e71e4819182f9186173987c94',locator='source/72_1.pdf digital53 left firstline enlarged crop; selected span only',source_sha256='8d33bb17e16dd87e562558bd5edbe56626501a0eb23a5a4680df7f7b26021828',claim={'key':'selected_fragment','value':'وحفظناها من كل شيطان'})
 request['evidence']=[witness]
 # Inspection has already occurred in this session. Record that retrospective
 # real result explicitly; do not imply the software reads manuscript pixels.
 decision=e.decide(request)
 if decision['selected_action']!='inspect_source':raise AssertionError('recovered correction did not affect selection')
 completed=e.complete(request['id'],{'status':'completed','selected_fragment':'وحفظناها من كل شيطان','full_sentence_status':'unresolved','review_artifact':'manual_fragments_v02.json'},verified=True,evidence=[witness],reason='retrospective record of actual enlarged visual inspection by assistant; runtime does not perform OCR')
 status=json.loads((a.book_output/'book_status.json').read_text())
 old=e.commitments()
 for promise in old:
  e.set_commitment(promise['id'],target=promise['target'],actual=status['combined_authored_tokens'] if promise['id']=='72div:word_target' else promise['actual'],source_ref=promise['source_ref'],locator=promise['locator'],status='open')
 for ident,target,actual,locator in [('stage2:contract_evaluation',20,20,'evidence/after.json final20'),('stage2:durability_checks',20,20,'evidence/durability_final/results.json'),('72div:source_unit_catalog',254,254,'page_ledger_v02.json'),('72div:final_edition_pages',100,0,'final 50000-word edition not yet produced')]:
  e.set_commitment(ident,target=target,actual=actual,source_ref='artifact://stage2-continuation',locator=locator,status='completed' if actual>=target else 'open')
 e.backup(a.output/'resume_checkpoint.sqlite');export=e.export();(a.output/'continuation_records.json').write_text(json.dumps(export,ensure_ascii=False,indent=2))
 probe=deepcopy(request);probe['id']='stage2-cold-probe';(a.output/'cold_request.json').write_text(json.dumps(probe))
 # Latest successful inspection is independent from the original failed acceptance action.
 before=e.decide(probe)
code="from pathlib import Path;import json,sys;from reflection_cycle import ReflectionCycle;r=json.loads(Path(sys.argv[2]).read_text());e=ReflectionCycle(sys.argv[1]);print(json.dumps({'decision':e.decide(r),'commitments':e.commitments()}));e.close()"
cold=subprocess.run([sys.executable,'-c',code,str((a.output/'resume_checkpoint.sqlite').resolve()),str((a.output/'cold_request.json').resolve())],cwd=ROOT,capture_output=True,text=True,check=True);result=json.loads(cold.stdout)
assert result['decision']['selected_action']==before['selected_action'];assert any(x['id']=='72div:word_target' and x['actual']==7132 and x['remaining']==42868 and x['status']=='open' for x in result['commitments'])
assert hashlib.sha256(a.source_ledger.read_bytes()).hexdigest()==source_hash
(a.output/'cold_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({'cold_action':result['decision']['selected_action'],'recalled':result['decision']['recalled_feedback_ids'],'source_ledger_unchanged':True,'book_actual':7132,'book_remaining':42868},ensure_ascii=False))
