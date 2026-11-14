"""Independent reconstruction of a completed cold-readback journal from its primary receipts."""
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

from examples.nasuraya_research.evidence_lineage import decide_claim

source, output = map(Path, sys.argv[1:3])
journal = [json.loads(s) for s in (source/'ledger.jsonl').read_text().splitlines()]
schedule = ('first','replay_one','replay_two','second','replay_three','failed','replay_final')
assert tuple(j['step'] for j in journal) == schedule
assert len({j["pid"] for j in journal}) == len(journal)
observations, receipts, events = [], {}, []
for entry in journal:
    step = entry['step']
    is_replay = step.startswith('replay')
    path = ('first' if is_replay else step) + '/receipt.json'
    assert entry['source'] == path
    raw = (source/path).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == entry['sha256']
    primary = json.loads(raw)
    for name, hash_key in [('reference.bin','expected_sha256'), ('working.bin','after_recovery_sha256')]:
        assert hashlib.sha256((source/Path(path).parent/name).read_bytes()).hexdigest() == primary[hash_key]
    assert primary['expected_sha256'] != primary['damaged_sha256']
    verdict = 'support' if primary['expected_sha256'] == primary['after_recovery_sha256'] else 'oppose'
    assert primary['observation']['verdict'] == verdict
    observation = dict(primary['observation'])
    if is_replay:
        observation.update(kind='replay', receipt_id=step+'-'+observation['root_id'])
    assert observation == entry['row']
    observations.append(observation)
    assert decide_claim(observations) == entry['decision']
    receipts[path] = {'sha256':entry['sha256'], 'receipt':primary}
    events.append({'step':step,'utc':entry['utc'],'pid':entry['pid'],'source':path,'decision':entry['decision']})
times = [datetime.fromisoformat(e['utc']) for e in events]
assert all(a < b for a,b in zip(times,times[1:]))
expected = [(1,0),(1,0),(1,0),(2,0),(2,0),(2,1),(2,1)]
assert [(e['decision']['support'],e['decision']['oppose']) for e in events] == expected
assert len(receipts) == len({v['receipt']['observation']['root_id'] for v in receipts.values()}) == 3
result={'scope':'Seven fresh local processes on one host, three deliberately induced disk recoveries and four readbacks of the first receipt. UTC timestamps are host observations. A new process does not make a new original recovery.',
        'implementation':'042f2b139e55b6fc598d26e48e19ead93ee88298','elapsed_seconds':round((times[-1]-times[0]).total_seconds(),3),
        'events':events,'original_receipts':receipts}
output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print('Verified',len(events),'events from',len(receipts),'primary receipts in',result['elapsed_seconds'],'seconds.')
