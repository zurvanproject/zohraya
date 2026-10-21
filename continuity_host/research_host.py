"""Research worker using the existing shared absence gate and GitHub ledger.

No new scheduler or allowance. Initialization is an explicit operator action;
unknown worker/CAS outcomes keep the existing inflight barrier, without refunds.
"""
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError

from continuity_host import host
from continuity_host import research_lab as lab

ANCHOR = 'research_v1_sha256'
MEMORY_PATH = 'continuity/research-v1.json'
WORKER_SECONDS = 45


class ResearchGitHub(host.GitHub):
    def raw_snapshot(self):
        return super().snapshot()

    def memory_exists(self, snapshot):
        try:
            self.call('GET', 'contents/'+MEMORY_PATH+'?ref='+snapshot['head'])
            return True
        except HTTPError as error:
            if error.code != 404:
                raise
            return False

    def snapshot(self):
        snapshot = self.raw_snapshot()
        anchor = snapshot['state'].get(ANCHOR)
        if not isinstance(anchor, str) or not re.fullmatch(r'[0-9a-f]{64}', anchor):
            raise ValueError('research not initialized or anchor invalid')
        item = self.call('GET', 'contents/'+MEMORY_PATH+'?ref='+snapshot['head'])
        memory = json.loads(base64.b64decode(item['content']))
        if lab.digest(memory) != anchor:
            raise ValueError('research memory anchor mismatch')
        lab.validate(memory)
        snapshot['memory'] = memory
        return snapshot

    def save_research(self, snapshot, state, memory, report=None):
        lab.validate(memory)
        state = deepcopy(state)
        state[ANCHOR] = lab.digest(memory)
        files = {'continuity/state.json': host.encode(state)+'\n',
                 MEMORY_PATH: lab.encode(memory)+'\n'}
        if report is not None:
            if not re.fullmatch(r'gh_[0-9]{1,30}_[0-9]{1,4}', report['run_id']):
                raise ValueError('report run id')
            files['continuity/runs/'+report['run_id']+'.json'] = lab.encode(report)+'\n'
        tree = self.call('POST', 'git/trees', dict(base_tree=snapshot['tree'], tree=[
            dict(path=name, mode='100644', type='blob', content=text)
            for name, text in files.items()]))
        commit = self.call('POST', 'git/commits', dict(message='Record bounded research state',
            tree=tree['sha'], parents=[snapshot['head']]))
        self.call('PATCH', 'git/refs/heads/'+host.BRANCH, dict(sha=commit['sha'], force=False))
        return commit['sha']


def initialize(api, gate):
    snapshot = api.raw_snapshot()
    state = snapshot['state']
    if ANCHOR in state or state['inflight_run_id'] is not None or api.memory_exists(snapshot):
        raise ValueError('no reinitialization or initialization during a pending run')
    # Operator presence is recorded, but the consumed budget is NOT reset.
    state = gate.operator_contact(state, host.now())
    commit = api.save_research(snapshot, state, lab.initial())
    return dict(status='initialized', commit=commit, scheduled_now=False)


def worker(memory, run_id):
    child = subprocess.run([sys.executable, '-I', str(Path(lab.__file__).resolve())],
        input=lab.encode(dict(memory=memory, run_id=run_id)),
        env={'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'},
        capture_output=True, text=True, timeout=WORKER_SECONDS)
    if child.returncode != 0:
        raise RuntimeError('research child failed; preserve unknown-outcome barrier')
    if len(child.stdout) > 1_000_000:
        raise ValueError('oversized research output')
    return json.loads(child.stdout)


def run(api, gate, run_id, execute=worker):
    if not re.fullmatch(r'gh_[0-9]{1,30}_[0-9]{1,4}', run_id):
        raise ValueError('run id')
    initial = api.snapshot()
    decision = gate.evaluate(initial['state'], host.now())
    if not decision['eligible']:
        return dict(status='deferred', reason=decision['reason'])
    lab.validate(initial['memory'])
    if len(initial['memory']['history']) == len(lab.FEATURES):
        return dict(status='curriculum_complete', reason='owner_review_new_curriculum')
    original_hash = lab.digest(initial['memory'])
    started = host.now()
    claimed = gate.claim(initial['state'], started, run_id)
    claim_commit = api.save_research(initial, claimed, initial['memory'])
    before = api.snapshot()
    if before['state']['inflight_run_id'] != run_id or lab.digest(before['memory']) != original_hash:
        raise ValueError('claim or memory ownership lost')
    contact = claimed['last_contact_at']
    cancelled = not before['state']['enabled'] or before['state']['last_contact_at'] != contact
    proposed = initial['memory']
    result = dict(passed=False, reason='operator_contact')
    if not cancelled:
        try:
            output = execute(deepcopy(initial['memory']), run_id)
            expected_memory, expected_receipt = lab.advance(initial['memory'], run_id)
            if lab.encode(output) != lab.encode(dict(memory=expected_memory, receipt=expected_receipt)):
                raise ValueError('worker result does not replay')
            proposed = output['memory']
            result = dict(passed=True, receipt=output['receipt'])
        except subprocess.TimeoutExpired:
            result = dict(passed=False, reason='worker_timeout_killed_and_reaped')
    # Unexpected errors keep the durable claim. Never silently retry or refund.
    final = api.snapshot()
    if final['state']['inflight_run_id'] != run_id or lab.digest(final['memory']) != original_hash:
        raise ValueError('claim or memory ownership lost')
    contact_changed = final['state']['last_contact_at'] != contact
    paused = not final['state']['enabled']
    learn = result['passed'] and not contact_changed and not paused and not cancelled
    memory = proposed if learn else initial['memory']
    ended = host.now()
    report = dict(schema='nasuraya-research-run/1', run_id=run_id,
        started_at=started, ended_at=ended, claim_commit=claim_commit,
        engine=lab.engine_digest(), gate_source=host.SOURCE,
        runner_source=os.environ.get('GITHUB_SHA'), result=result, memory_updated=learn,
        contact_changed=contact_changed, paused=paused, model_api_used=False,
        financial_actions=0, canonical_body_changed=False,
        scope='Finite synthetic recall research; generated policy remains laboratory-only')
    completed = gate.finish(final['state'], ended, run_id)
    commit = api.save_research(final, completed, memory, report)
    return dict(status='recorded', commit=commit, result=result, memory_updated=learn)


def main():
    if os.environ.get('GITHUB_REPOSITORY') != host.REPO:
        raise ValueError('repository restriction')
    if os.environ.get('GITHUB_REF') != 'refs/heads/main' or os.environ.get('GITHUB_EVENT_NAME') not in ('schedule', 'workflow_dispatch'):
        raise ValueError('live research requires the reviewed default branch')
    source = Path(sys.argv[1]).resolve()
    if subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip() != host.SOURCE:
        raise ValueError('gate source must equal pinned commit')
    if host.digest((source/'continuity/gate.py').read_bytes()) != host.GATE_HASH:
        raise ValueError('pinned gate integrity')
    sys.path.insert(0, str(source))
    from continuity import gate
    mode = os.environ.get('RESEARCH_MODE', 'auto')
    api = ResearchGitHub()
    if mode == 'initialize':
        if os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch':
            raise ValueError('initialization requires explicit operator dispatch')
        result = initialize(api, gate)
    elif mode == 'auto':
        run_id = 'gh_'+os.environ['GITHUB_RUN_ID']+'_'+os.environ['GITHUB_RUN_ATTEMPT']
        raw = api.raw_snapshot()
        # Until explicitly initialized, preserve the original fixed regression.
        result = (run(api, gate, run_id) if ANCHOR in raw['state'] else
                  host.run(host.GitHub(), gate, source, run_id))
    else:
        raise ValueError('unknown research mode')
    print(lab.encode(result))


if __name__ == '__main__':
    main()
