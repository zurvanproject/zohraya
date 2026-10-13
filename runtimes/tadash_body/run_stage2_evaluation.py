"""Run frozen requests against a specified baseline or current engine."""
import argparse, hashlib, json, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--engine-root',type=Path,default=ROOT);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
sys.path.insert(0,str(a.engine_root.resolve()))
from reflection_cycle import ReflectionCycle, core_action
from decision_core import DecisionCore
raw=(ROOT/'stage2_cases.json').read_bytes();checksum=(ROOT/'stage2_cases.sha256').read_text().strip()
assert hashlib.sha256(raw).hexdigest()==checksum
frozen=json.loads(raw);rows=[]
for c in frozen['cases']:
 row=dict(id=c['id'],split=c['split'],type=c['type'],expected=c['expected'])
 base=DecisionCore().decide(tuple(core_action(x) for x in c['request']['actions'])).to_dict()
 row['core']={'selected':base['selected_action'],'passed':base['selected_action']==c['expected']}
 for memory in [False,True]:
  with tempfile.TemporaryDirectory() as tmp, ReflectionCycle(Path(tmp)/'ledger.sqlite',use_memory=memory) as engine:
   for h in c['history']:
    engine.decide(h['request']);engine.complete(h['request']['id'],h['actual_outcome'],verified=h['verified'],evidence=h['evidence'],reason=h['reason'])
   d=engine.decide(c['request']);row['memory' if memory else 'gates']=dict(selected=d['selected_action'],passed=d['selected_action']==c['expected'],record=d)
 rows.append(row)
summary=dict(criteria_sha256=checksum,engine_sha256=hashlib.sha256((a.engine_root/'reflection_cycle.py').read_bytes()).hexdigest(),reference_provenance=frozen['reference_provenance'],counts={split:{k:sum(x[k]['passed'] for x in rows if x['split']==split) for k in ['core','gates','memory']} for split in ['development','final']},totals={s:sum(x['split']==s for x in rows) for s in ['development','final']},memory_only=[x['id'] for x in rows if x['memory']['passed'] and not x['gates']['passed']],memory_regressions=[x['id'] for x in rows if x['gates']['passed'] and not x['memory']['passed']],records=rows)
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in summary.items() if k!='records'},indent=2))
