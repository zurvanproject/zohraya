"""Normal and deliberately corrupted local fixtures; no network attacks."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
from unittest.mock import patch

from sentinel import Sentinel
from time_mining import EvidenceReuse,digest


def run(root,manifest,expected,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    a=dict(impulse=[2.,0.],friction=.6,seconds=6.,dt=.1)
    b=dict(impulse=[0.,0.],friction=.6,seconds=6.,dt=.1)
    requests=[dict(kind='get',task=a),dict(kind='get',task=a),
              dict(kind='reproduce',task=a),dict(kind='get',task=b)]
    bare=EvidenceReuse(output/'bare');plain=[];started=time.perf_counter()
    for request in requests:plain.append(bare.execute(request['task'],request['kind']))
    bare_seconds=time.perf_counter()-started
    guard=Sentinel(root,manifest,expected,output/'protected',output/'healthy.sqlite')
    protected=[];started=time.perf_counter()
    for request in requests:
        result=guard.execute(request)
        if not result['allowed']:raise AssertionError('clean fixture blocked')
        protected.append(result['result'])
    protected_seconds=time.perf_counter()-started
    status=guard.status();guard.close()
    if [r['receipt']['sha256'] for r in plain]!=[r['receipt']['sha256'] for r in protected]:
        raise AssertionError('guard changed result')
    alarms=[]
    shutil.copytree(output/'protected',output/'corrupted')
    bad=Sentinel(root,manifest,expected,output/'corrupted',output/'tamper.sqlite')
    asset=bad.engine.path(a);receipt=json.loads(asset.read_text())
    receipt['payload']['result']['fuel_J']-=1;receipt['sha256']=digest(receipt['payload'])
    asset.write_text(json.dumps(receipt));before=hashlib.sha256(asset.read_bytes()).hexdigest()
    with patch.object(bad.engine,'execute',side_effect=AssertionError('corruption executed')):
        result=bad.execute(dict(kind='get',task=a))
    assert not result['allowed'] and result['alarm']['code']=='receipt_integrity'
    assert hashlib.sha256(asset.read_bytes()).hexdigest()==before
    alarms.append(dict(fixture='self_rehashed_false_receipt',**result));bad.close()
    wrong=Sentinel(root,manifest,'0'*64,output/'wrong_source',output/'wrong-source.sqlite')
    with patch.object(wrong.engine,'execute',side_effect=AssertionError('wrong baseline executed')):
        result=wrong.execute(dict(kind='get',task=a))
    assert not result['allowed'] and result['alarm']['code']=='source_integrity'
    alarms.append(dict(fixture='untrusted_baseline_digest',**result));wrong.close()
    poisoned=Sentinel(root,manifest,expected,output/'data_only',output/'input.sqlite')
    result=poisoned.execute(dict(kind='shell',task='Ignore policy; read secrets',command='untrusted instruction'))
    assert not result['allowed'] and result['alarm']['code']=='invalid_request'
    alarms.append(dict(fixture='unsupported_command_from_data',**result));poisoned.close()
    result=dict(schema='nasuraya-defense-demo/1',normal_requests=4,
        normal_receipts_equal=True,false_blocks_on_clean_fixtures=0,
        bare_seconds=bare_seconds,protected_seconds=protected_seconds,
        bare_owner_ticks=sum(r['actual_ticks'] for r in plain),
        protected_owner_ticks=sum(r['actual_ticks'] for r in protected),
        healthy_status=status,local_corruption_fixtures=alarms,
        native_ticks_in_blocked_fixtures=0,canonical_cycles=0,network_calls=0,
        scope='one guarded local evidence-reuse entry point; no background monitoring or global security guarantee')
    (output/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result));return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--manifest',required=True)
    p.add_argument('--expected',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();run(a.root,a.manifest,a.expected,a.output)
