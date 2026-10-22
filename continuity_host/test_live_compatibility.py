"""Exercise the live readers against an unmigrated, read-only control branch.

Only the HTTP transport is replaced. Inherited snapshots, policy/gate hashes,
memory anchors, source validation and auto-mode routing use production code.
"""
import base64
from contextlib import redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlsplit

from continuity_host import host, model_research as model
from continuity_host import research_host as research, research_lab as lab


SOURCE = Path(os.environ.get('NASURAYA_TEST_SOURCE', 'source')).resolve()
NOW = '2026-10-22T01:00:00+00:00'
CONTACT = '2026-10-22T00:00:00+00:00'


class ReadOnlyControlBranch:
    """A GitHub GET fixture with no cadence ledger or write endpoints."""

    head = 'a' * 40
    tree = 'b' * 40

    def __init__(self, state, memory_path, memory):
        self.calls = []
        self.files = {
            'continuity/policy.json': (SOURCE / 'continuity/policy.json').read_bytes(),
            'continuity/gate.py': (SOURCE / 'continuity/gate.py').read_bytes(),
            'continuity/state.json': lab.encode(state).encode(),
            memory_path: lab.encode(memory).encode(),
        }

    def __call__(self, request, timeout):
        url = urlsplit(request.full_url)
        prefix = '/repos/' + host.REPO + '/'
        path = unquote(url.path)
        if url.scheme != 'https' or url.netloc != 'api.github.com' or not path.startswith(prefix):
            raise AssertionError('Unexpected network destination in compatibility test')
        route = path[len(prefix):]
        self.calls.append(route)
        if 'cadence' in route:
            raise AssertionError('Live state has no cadence migration or ledger')
        if request.get_method() != 'GET' or request.data is not None:
            raise AssertionError('Compatibility read must not mutate the control branch')
        if route == 'git/ref/heads/' + host.BRANCH:
            payload = {'object': {'sha': self.head}}
        elif route == 'git/commits/' + self.head:
            payload = {'tree': {'sha': self.tree}}
        elif route.startswith('contents/'):
            if parse_qs(url.query) != {'ref': [self.head]}:
                raise AssertionError('Every file must be read at the captured branch head')
            name = route[len('contents/'):]
            if name not in self.files:
                raise AssertionError('Unexpected control-branch file: ' + name)
            payload = {'content': base64.b64encode(self.files[name]).decode()}
        else:
            raise AssertionError('Unexpected GitHub route: ' + route)
        return io.BytesIO(json.dumps(payload).encode())


class LiveCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            'compatibility_pinned_gate', SOURCE / 'continuity/gate.py')
        cls.gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.gate)

    def make_branch(self, engine):
        memory = model.initial() if engine is model else lab.initial()
        state = dict(schema=self.gate.SCHEMA, enabled=True,
                     last_contact_at=CONTACT, last_claimed_at=None,
                     inflight_run_id=None, last_completed_run_id=None,
                     **{engine.ANCHOR: lab.digest(memory)})
        self.assertNotIn('cadence_sha256', state)
        return ReadOnlyControlBranch(state, engine.MEMORY_PATH, memory), state, memory

    def check_reader(self, engine, reader):
        branch, state, memory = self.make_branch(engine)
        original = deepcopy(branch.files)
        with patch.dict(os.environ, {'GH_HOST_TOKEN': 'offline-fixture-token'}), \
                patch.object(host.urllib.request, 'urlopen', side_effect=branch):
            snapshot = reader().snapshot()
        self.assertEqual(snapshot['state'], state)
        self.assertEqual(snapshot['memory'], memory)
        self.assertEqual(snapshot['head'], branch.head)
        self.assertEqual(snapshot['tree'], branch.tree)
        self.assertNotIn('ledger', snapshot)
        self.assertEqual(branch.files, original)
        self.assertIn('contents/' + engine.MEMORY_PATH, branch.calls)

    def test_model_reader_accepts_existing_state_without_cadence(self):
        self.check_reader(model, model.ModelGitHub)

    def test_research_reader_accepts_existing_state_without_cadence(self):
        self.check_reader(research, research.ResearchGitHub)

    def test_auto_mode_reads_model_memory_and_preserves_recent_contact_gate(self):
        branch, state, memory = self.make_branch(model)
        original = deepcopy(branch.files)
        output = io.StringIO()
        env = dict(GH_HOST_TOKEN='offline-fixture-token',
                   GITHUB_REPOSITORY=host.REPO, GITHUB_REF='refs/heads/main',
                   GITHUB_EVENT_NAME='schedule', GITHUB_RUN_ID='910',
                   GITHUB_RUN_ATTEMPT='1', RESEARCH_MODE='auto')
        with patch.dict(os.environ, env), \
                patch.object(sys, 'argv', ['research_host', str(SOURCE)]), \
                patch.object(sys, 'path', list(sys.path)), \
                patch.object(host, 'now', return_value=NOW), \
                patch.object(host.urllib.request, 'urlopen', side_effect=branch), \
                patch.object(model, 'call_model', side_effect=AssertionError('No model call is eligible')), \
                redirect_stdout(output):
            research.main()
        self.assertEqual(json.loads(output.getvalue()),
                         {'status': 'deferred', 'reason': 'recent_contact'})
        self.assertIn('contents/' + model.MEMORY_PATH, branch.calls)
        self.assertEqual(branch.files, original)
        self.assertEqual(json.loads(branch.files['continuity/state.json']), state)
        self.assertEqual(json.loads(branch.files[model.MEMORY_PATH]), memory)


if __name__ == '__main__':
    unittest.main()
