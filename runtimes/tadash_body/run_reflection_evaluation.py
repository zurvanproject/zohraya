"""Paired comparison on predeclared synthetic contract scenarios."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from decision_core import DecisionCore
from reflection_cycle import ReflectionCycle,core_action

ROOT=Path(__file__).resolve().parent

def evaluate(output):
    raw=(ROOT/'reflection_cases.json').read_bytes()
    expected=(ROOT/'reflection_cases.sha256').read_text().strip()
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('preregistered fixture changed')
    criteria=json.loads(raw);records=[]
    for c in criteria['cases']:
        baseline=DecisionCore().decide(tuple(core_action(a) for a in c['request']['actions'])).to_dict()
        row=dict(case_id=c['id'],expected=c['expected'],existing_core=dict(selected=baseline['selected_action'],passed=baseline['selected_action']==c['expected'],record=baseline))
        for memory in [False,True]:
            with tempfile.TemporaryDirectory() as tmp,ReflectionCycle(Path(tmp)/'ledger.sqlite',use_memory=memory) as engine:
                t=c['training']
                if t:
                    engine.decide(t['request'])
                    engine.complete(t['request']['id'],t['actual_outcome'],verified=True,evidence=t['feedback_evidence'],reason='verified frozen training fixture')
                decision=engine.decide(c['request'])
                row['reflection_with_memory' if memory else 'reflection_without_memory']=dict(selected=decision['selected_action'],passed=decision['selected_action']==c['expected'],record=decision)
        records.append(row)
    names=('existing_core','reflection_without_memory','reflection_with_memory')
    summary=dict(schema='tadash-reflection-evaluation/1',criteria_sha256=expected,scenario_count=len(records),
        correct={name:sum(r[name]['passed'] for r in records) for name in names},
        memory_only_cases=[r['case_id'] for r in records if not r['reflection_without_memory']['passed'] and r['reflection_with_memory']['passed']],
        fixture_scope='constructed deterministic scenarios frozen before implementation; not a blinded/general capability benchmark',
        calibrated_probabilities=False,model_weights_modified=False,records=records)
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    (output/'comparison.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();s=evaluate(a.output)
    print(json.dumps({k:v for k,v in s.items() if k!='records'},indent=2))
    raise SystemExit(0 if s['correct']['reflection_with_memory']==s['scenario_count'] else 1)
