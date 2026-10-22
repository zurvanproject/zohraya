"""Experimental six-hour host; requires explicitly migrated cadence state."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request
from continuity_host import cadence

REPO = 'zurvanproject/zohraya'
BRANCH = 'nasuraya/absence-continuity-v01'
SOURCE = '7aaee60198b50246d90242d5155d3e3736882792'
POLICY_HASH = '37bbfc159e7da4d57656c7c527c94601b7ab2a9afd96bb5b696da405c1ead34e'
GATE_HASH = '26a082342b44cca50623c8134ea7ce63981425b27e6d997ed81c9bc39721bcf4'
RUN_SECONDS = 60


def now(): return datetime.now(timezone.utc).isoformat()
def digest(raw): return hashlib.sha256(raw).hexdigest()
def encode(value): return json.dumps(value, sort_keys=True, ensure_ascii=True)


class GitHub:
    def call(self, method, path, data=None):
        request = urllib.request.Request('https://api.github.com/repos/'+REPO+'/'+path,
            data=encode(data).encode() if data is not None else None, method=method,
            headers={'Authorization':'Bearer '+os.environ['GH_HOST_TOKEN'],
                     'Accept':'application/vnd.github+json','Content-Type':'application/json'})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    def snapshot(self):
        head = self.call('GET', 'git/ref/heads/'+BRANCH)['object']['sha']
        commit = self.call('GET', 'git/commits/'+head)
        def read(name):
            item = self.call('GET', 'contents/continuity/'+name+'?ref='+head)
            return base64.b64decode(item['content'], validate=False)
        if digest(read('policy.json')) != POLICY_HASH or digest(read('gate.py')) != GATE_HASH:
            raise ValueError('control policy or gate drift; no claim')
        return dict(head=head, tree=commit['tree']['sha'], state=json.loads(read('state.json')),
                    ledger=json.loads(read('cadence-v2.json')))

    def save(self, snapshot, state, report=None, ledger=None):
        files = {'continuity/state.json':encode(state)+'\n'}
        if ledger is not None: files['continuity/cadence-v2.json']=encode(ledger)+'\n'
        if report is not None:
            files['continuity/runs/'+report['run_id']+'.json'] = encode(report)+'\n'
        tree = self.call('POST','git/trees',dict(base_tree=snapshot['tree'], tree=[
            dict(path=name, mode='100644', type='blob', content=text) for name,text in files.items()]))
        commit = self.call('POST','git/commits',dict(message='Record bounded GitHub host '+
            ('result' if report else 'claim'),tree=tree['sha'],parents=[snapshot['head']]))
        # A single parent and force=false reject a competing non-ancestor head.
        self.call('PATCH','git/refs/heads/'+BRANCH,dict(sha=commit['sha'],force=False))
        return commit['sha']


def probe(source):
    code = '''import json,unittest
from nasuraya_continuity_kit.verify_local_job import deny_network
denied=deny_network()
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in
 ('continuity.test_gate','nasuraya_continuity_kit.test_store','nasuraya_continuity_kit.test_local_job'))
r=unittest.TextTestRunner(verbosity=2).run(suite)
print(json.dumps(dict(passed=r.wasSuccessful() and r.testsRun==36 and not r.skipped,tests=r.testsRun,
 failures=len(r.failures),errors=len(r.errors),skips=len(r.skipped),network_syscalls_denied=denied)))
'''
    # The pinned child receives no GitHub token, model key or credential helper.
    child = subprocess.run([sys.executable,'-c',code], cwd=source, timeout=RUN_SECONDS,
        env={'PATH':os.defpath,'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1'},
        capture_output=True, text=True)
    if child.returncode: return dict(passed=False,reason='probe_failed',exit_code=child.returncode)
    return json.loads(child.stdout.strip().splitlines()[-1])


def run(api, gate, source, run_id, execute=probe):
    if not re.fullmatch(r'gh_[0-9]{1,30}_[0-9]{1,4}',run_id): raise ValueError('run id')
    initial = api.snapshot(); started = now()
    decision = cadence.evaluate(gate,initial['state'],initial['ledger'],started)
    if not decision['eligible']: return dict(status='deferred',reason=decision['reason'])
    claimed,reserved,budget = cadence.claim(gate,initial['state'],initial['ledger'],started,run_id)
    claim_commit = api.save(initial,claimed,ledger=reserved)  # Atomic budget+claim.
    before = api.snapshot()
    cadence.synchronize(gate,before['state'],before['ledger'],now())
    if before['state']['inflight_run_id'] != run_id: raise ValueError('claim ownership lost')
    contact = claimed['last_contact_at']
    cancelled = not before['state']['enabled'] or before['state']['last_contact_at'] != contact
    try: result = dict(passed=False,reason='operator_contact') if cancelled else execute(source)
    except subprocess.TimeoutExpired: result = dict(passed=False,reason='probe_timeout_killed_and_reaped')
    # Unexpected errors deliberately leave the durable inflight barrier intact.
    final = api.snapshot(); ended = now()
    cadence.synchronize(gate,final['state'],final['ledger'],ended)
    if final['state']['inflight_run_id'] != run_id: raise ValueError('claim ownership lost')
    report = dict(schema='nasuraya-github-host-run/1',run_id=run_id,started_at=started,
        ended_at=ended,source_commit=SOURCE,claim_commit=claim_commit,result=result,
        contact_changed=final['state']['last_contact_at'] != contact,
        paused=not final['state']['enabled'],reserved_budget=budget,model_api_used=False,financial_actions=0,
        scope='Fixed synthetic regression tests; no canonical body or experience mutation')
    completed = gate.finish(final['state'],ended,run_id)  # Preserve pause/contact/budget.
    saved = api.save(final,completed,report)
    return dict(status='recorded',commit=saved,result=result)


def main():
    source = Path(sys.argv[1]).resolve()
    if subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip() != SOURCE:
        raise ValueError('source checkout must equal pinned commit')
    if digest((source/'continuity/gate.py').read_bytes()) != GATE_HASH:
        raise ValueError('pinned gate integrity')
    sys.path.insert(0,str(source))
    from continuity import gate
    if os.environ.get('GITHUB_REPOSITORY') != REPO: raise ValueError('repository restriction')
    print(encode(run(GitHub(),gate,source,'gh_'+os.environ['GITHUB_RUN_ID']+'_'+os.environ['GITHUB_RUN_ATTEMPT'])))


if __name__ == '__main__': main()
