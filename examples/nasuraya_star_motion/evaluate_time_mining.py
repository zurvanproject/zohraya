"""Pair no-reuse and checked-reuse on identical typed native-result requests."""
import hashlib
import json
from pathlib import Path
import time
from time_mining import EvidenceReuse,digest,sources


def run(protocol_path,output):
    protocol_path=Path(protocol_path);p=json.loads(protocol_path.read_text())
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    origin=sources();arms={}
    # Both stores start empty. Cost of producing reusable evidence is included.
    for name,reuse in [('recompute',False),('reuse',True)]:
        store=EvidenceReuse(output/name);rows=[];started=time.perf_counter()
        for request in p['requests']:
            task=p['tasks'][request['task']];t=time.perf_counter()
            answer=store.execute(task,request['kind'],reuse=reuse)
            rows.append(dict(request=request,mode=answer['mode'],actual_ticks=answer['actual_ticks'],
                receipt_sha256=answer['receipt']['sha256'],wall_seconds=time.perf_counter()-t))
        arms[name]=dict(rows=rows,actual_ticks=sum(r['actual_ticks'] for r in rows),wall_seconds=time.perf_counter()-started)
        print(json.dumps({'arm':name,'actual_ticks':arms[name]['actual_ticks'],'wall_seconds':arms[name]['wall_seconds']}),flush=True)
    equal=all(a['receipt_sha256']==b['receipt_sha256'] for a,b in zip(arms['recompute']['rows'],arms['reuse']['rows']))
    reproduce_ok=all(r['mode']=='fresh_reproduction' and r['actual_ticks']>0 for r in arms['reuse']['rows'] if r['request']['kind']=='reproduce')
    saving=1-arms['reuse']['actual_ticks']/arms['recompute']['actual_ticks']
    if sources()!=origin:raise AssertionError('source changed during experiment')
    result=dict(schema='nasuraya-time-mining-evaluation/1',protocol=p,
        protocol_sha256=hashlib.sha256(protocol_path.read_bytes()).hexdigest(),source_manifest=origin,
        arms=arms,all_result_receipts_equal=equal,explicit_reproductions_executed=reproduce_ok,
        native_tick_saving=saving,
        accepted=equal and reproduce_ok and saving>=p['minimum_tick_saving'],
        canonical_cycles=0,api_calls=0,
        limits=['Authored repetition workload, not general intelligence or independent learning evidence.',
         'Reuse returns a previous verified result, not a new observation or a dynamics reproduction.',
         'Runtime timings are one local run, not a controlled hardware benchmark.',
         'Single-process experiment; no concurrency, crash recovery or background service.'])
    (output/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('arms','protocol','source_manifest','limits')}),flush=True)
    return result


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--protocol',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();run(a.protocol,a.output)
