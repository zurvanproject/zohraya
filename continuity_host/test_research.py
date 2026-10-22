import base64
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from continuity_host import host
from continuity_host import research_lab as lab
from continuity_host import research_host as runtime

SOURCE = Path(os.environ.get('NASURAYA_TEST_SOURCE', 'source')).resolve()
spec = importlib.util.spec_from_file_location('research_test_gate', SOURCE/'continuity/gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
START = '2026-10-16T10:00:00Z'
DUE = '2026-10-17T10:00:00Z'


class LabTests(unittest.TestCase):
    def test_four_rounds_then_stops(self):
        memory = lab.initial()
        features = []
        for i in range(4):
            memory, receipt = lab.advance(memory, 'trial_'+str(i))
            trial = receipt['trial']
            features.append(trial['feature'])
            self.assertTrue(trial['accepted'])
            self.assertLess(trial['holdout']['after']['errors'], trial['holdout']['before']['errors'])
        self.assertEqual(features, ['freshness', 'context', 'trusted', 'conflict'])
        self.assertEqual(lab.evaluate(memory['policy'], lab.cases(9261022, 48))['errors'], 0)
        unchanged, result = lab.advance(memory, 'trial_4')
        self.assertEqual(unchanged, memory)
        self.assertEqual(result['status'], 'curriculum_complete')

    def test_replay_does_not_rewind_latest_policy(self):
        memory, first = lab.advance(lab.initial(), 'one')
        memory, _ = lab.advance(memory, 'two')
        replayed, receipt = lab.advance(memory, 'one')
        self.assertEqual(replayed, memory)
        self.assertEqual(receipt, first)

    def test_policy_without_evidence_rejected(self):
        memory = lab.initial()
        memory['policy']['trusted'] = True
        with self.assertRaises(ValueError): lab.validate(memory)

    def test_changed_receipt_rejected(self):
        memory, _ = lab.advance(lab.initial(), 'one')
        memory['history'][0]['trial']['holdout']['after']['errors'] = 0
        with self.assertRaises(ValueError): lab.validate(memory)

    def test_engine_drift_rejected(self):
        memory = lab.initial()
        memory['engine'] = '0'*64
        with self.assertRaises(ValueError): lab.validate(memory)

    def test_boolean_must_be_boolean(self):
        memory = lab.initial()
        memory['policy']['trusted'] = 0
        with self.assertRaises(ValueError): lab.validate(memory)

    def test_duplicate_history_rejected(self):
        memory, _ = lab.advance(lab.initial(), 'one')
        memory['history'].append(deepcopy(memory['history'][0]))
        with self.assertRaises(ValueError): lab.validate(memory)

    def test_parent_input_is_not_mutated(self):
        memory = lab.initial()
        original = deepcopy(memory)
        lab.advance(memory, 'one')
        self.assertEqual(memory, original)

    def test_train_and_validation_are_distinct(self):
        self.assertNotEqual(lab.digest(lab.cases(20261022, 32)), lab.digest(lab.cases(9261022, 48)))
        self.assertEqual(len(lab.cases(20261022, 32)), 192)
        self.assertEqual(len(lab.cases(9261022, 48)), 288)

    def test_future_and_conflict_abstain(self):
        policy = {name: True for name in lab.FEATURES}
        for row in lab.cases(9, 4):
            if row['kind'] in ('future', 'stale', 'conflict'):
                self.assertIsNone(lab.recall(policy, row))

    def test_validation_regression_rejects_candidate(self):
        real = lab.evaluate
        def shifted(policy, rows):
            result = real(policy, rows)
            if len(rows) == 288 and policy['freshness']:
                result['errors'] = 288
                result['by_kind']['clean'] = 48
            return result
        with patch.object(lab, 'evaluate', side_effect=shifted):
            memory, receipt = lab.advance(lab.initial(), 'bad')
            self.assertFalse(receipt['trial']['accepted'])
            self.assertEqual(memory['policy'], lab.BASELINE)
            self.assertNotEqual(lab.propose(memory['policy'], ['freshness'])['feature'], 'freshness')

    def test_invalid_id(self):
        for value in ('../escape', '', 'x'*81, None):
            with self.assertRaises(ValueError): lab.advance(lab.initial(), value)

    def test_real_cold_process_continuation(self):
        first = runtime.worker(lab.initial(), 'cold_1')
        second = runtime.worker(json.loads(lab.encode(first['memory'])), 'cold_2')
        self.assertEqual(second['receipt']['index'], 2)
        self.assertEqual(second['receipt']['trial']['feature'], 'context')
        self.assertTrue(second['memory']['policy']['freshness'])
        lab.validate(second['memory'])

    def test_child_receives_no_credentials(self):
        output = dict(memory=lab.initial(), receipt={})
        with patch.dict(os.environ, {'GH_HOST_TOKEN': 'secret', 'MODEL_KEY': 'secret'}):
            with patch.object(runtime.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, lab.encode(output))) as call:
                runtime.worker(lab.initial(), 'one')
        env = call.call_args.kwargs['env']
        self.assertNotIn('GH_HOST_TOKEN', env)
        self.assertNotIn('MODEL_KEY', env)
        self.assertEqual(call.call_args.kwargs['timeout'], 45)
        self.assertIn('-I', call.call_args.args[0])


class Fake:
    def __init__(self):
        self.memory = lab.initial()
        self.state = dict(schema=gate.SCHEMA, enabled=True, last_contact_at=START,
            last_claimed_at=None, inflight_run_id=None, last_completed_run_id=None,
            **{runtime.ANCHOR: lab.digest(self.memory)})
        self.head = 'initial'
        self.saved = []
        self.conflict = False
        self.pause_after_claim = False
        self.orphan_memory = False

    def raw_snapshot(self):
        if self.pause_after_claim and self.saved:
            self.state['enabled'] = False
        return dict(head=self.head, tree='tree', state=deepcopy(self.state))

    def memory_exists(self, snapshot):
        return self.orphan_memory or runtime.ANCHOR in self.state

    def snapshot(self):
        snapshot = self.raw_snapshot()
        if lab.digest(self.memory) != self.state.get(runtime.ANCHOR):
            raise ValueError('memory mismatch')
        lab.validate(self.memory)
        snapshot['memory'] = deepcopy(self.memory)
        return snapshot

    def save_research(self, snapshot, state, memory, report=None):
        if self.conflict or snapshot['head'] != self.head:
            raise RuntimeError('CAS conflict')
        lab.validate(memory)
        self.state = deepcopy(state)
        self.state[runtime.ANCHOR] = lab.digest(memory)
        self.memory = deepcopy(memory)
        self.head = 'commit_'+str(len(self.saved))
        self.saved.append(deepcopy(report))
        return self.head


class HostTests(unittest.TestCase):
    def setUp(self):
        self.api = Fake()
        clock = patch.object(host, 'now', return_value=DUE)
        clock.start()
        self.addCleanup(clock.stop)

    def execute(self, memory, run_id):
        result, receipt = lab.advance(memory, run_id)
        return dict(memory=result, receipt=receipt)

    def run_job(self, execute=None):
        return runtime.run(self.api, gate, 'gh_123_1', execute or self.execute)

    def test_claim_precedes_experiment_and_budget_shared(self):
        def execute(memory, run_id):
            self.assertEqual(self.api.state['inflight_run_id'], run_id)
            self.assertIsNone(self.api.saved[0])
            return self.execute(memory, run_id)
        self.assertTrue(self.run_job(execute)['memory_updated'])
        self.assertEqual(self.run_job()['reason'], 'daily_budget_used')
        self.assertEqual(gate.evaluate(self.api.state, DUE)['reason'], 'daily_budget_used')

    def test_paused_or_recent_contact_do_not_run(self):
        self.api.state['enabled'] = False
        self.assertEqual(self.run_job()['reason'], 'paused')
        self.api.state['enabled'] = True
        self.api.state['last_contact_at'] = DUE
        self.assertEqual(self.run_job()['reason'], 'recent_contact')
        self.assertEqual(self.api.saved, [])

    def test_claim_conflict_never_executes(self):
        self.api.conflict = True
        with self.assertRaises(RuntimeError):
            self.run_job(lambda *args: self.fail('unclaimed execution'))
        self.assertEqual(self.api.memory['history'], [])

    def test_unknown_result_keeps_barrier(self):
        def crash(*args): raise OSError('worker lost')
        with self.assertRaises(OSError): self.run_job(crash)
        self.assertEqual(self.api.state['inflight_run_id'], 'gh_123_1')
        self.assertEqual(self.run_job()['reason'], 'unresolved_previous_run')

    def test_pause_after_claim_cancels(self):
        self.api.pause_after_claim = True
        result = self.run_job(lambda *args: self.fail('paused execution'))
        self.assertFalse(result['memory_updated'])
        self.assertFalse(self.api.state['enabled'])
        self.assertEqual(self.api.memory['history'], [])

    def test_contact_during_experiment_discards_learning(self):
        def execute(memory, run_id):
            self.api.state['last_contact_at'] = DUE
            return self.execute(memory, run_id)
        self.assertFalse(self.run_job(execute)['memory_updated'])
        self.assertEqual(self.api.memory['history'], [])
        self.assertEqual(self.api.state['last_contact_at'], DUE)

    def test_pause_during_experiment_discards_learning(self):
        def execute(memory, run_id):
            self.api.state['enabled'] = False
            return self.execute(memory, run_id)
        self.assertFalse(self.run_job(execute)['memory_updated'])
        self.assertFalse(self.api.state['enabled'])

    def test_failed_final_cas_keeps_claim_and_old_memory(self):
        def execute(memory, run_id):
            self.api.conflict = True
            return self.execute(memory, run_id)
        with self.assertRaises(RuntimeError): self.run_job(execute)
        self.assertEqual(self.api.memory['history'], [])
        self.assertEqual(self.api.state['inflight_run_id'], 'gh_123_1')

    def test_timeout_consumes_budget_without_learning(self):
        def timeout(*args): raise subprocess.TimeoutExpired('lab', 45)
        result = self.run_job(timeout)
        self.assertEqual(result['result']['reason'], 'worker_timeout_killed_and_reaped')
        self.assertFalse(result['memory_updated'])
        self.assertEqual(self.run_job()['reason'], 'daily_budget_used')

    def test_fabricated_worker_result_rejected(self):
        def fake(memory, run_id):
            output = self.execute(memory, run_id)
            output['receipt']['trial']['accepted'] = False
            return output
        with self.assertRaises(ValueError): self.run_job(fake)
        self.assertIsNotNone(self.api.state['inflight_run_id'])
        self.assertEqual(self.api.memory['history'], [])

    def test_corrupted_memory_stops_before_claim(self):
        self.api.memory['policy']['trusted'] = True
        with self.assertRaises(ValueError): self.run_job()
        self.assertEqual(self.api.saved, [])

    def test_complete_curriculum_does_not_consume_new_slot(self):
        for index in range(4):
            self.api.memory, _ = lab.advance(self.api.memory, 'demo_'+str(index))
        self.api.state[runtime.ANCHOR] = lab.digest(self.api.memory)
        self.assertEqual(self.run_job()['status'], 'curriculum_complete')
        self.assertEqual(self.api.saved, [])

    def test_initialize_preserves_pause_and_consumed_budget(self):
        del self.api.state[runtime.ANCHOR]
        self.api.state['last_claimed_at'] = START
        self.api.state['enabled'] = False
        result = runtime.initialize(self.api, gate)
        self.assertEqual(result['status'], 'initialized')
        self.assertFalse(self.api.state['enabled'])
        self.assertEqual(self.api.state['last_claimed_at'], START)
        self.assertEqual(gate.timestamp(self.api.state['last_contact_at']), gate.timestamp(DUE))

    def test_initialize_refuses_existing_or_unresolved_state(self):
        with self.assertRaises(ValueError): runtime.initialize(self.api, gate)
        del self.api.state[runtime.ANCHOR]
        self.api.state['inflight_run_id'] = 'previous'
        with self.assertRaises(ValueError): runtime.initialize(self.api, gate)
        self.api.state['inflight_run_id'] = None
        self.api.orphan_memory = True
        with self.assertRaises(ValueError): runtime.initialize(self.api, gate)

    def test_real_worker_through_host(self):
        self.assertTrue(self.run_job(runtime.worker)['memory_updated'])
        self.assertEqual(self.api.memory['history'][0]['trial']['feature'], 'freshness')


class BackendTests(unittest.TestCase):
    def test_atomic_tree_uses_only_fixed_paths_and_nonforce_ref(self):
        api = runtime.ResearchGitHub()
        calls = []
        def call(method, path, data=None):
            calls.append((method, path, data))
            return dict(sha='tree' if path == 'git/trees' else 'commit')
        with patch.object(api, 'call', side_effect=call):
            api.save_research(dict(tree='oldtree', head='oldhead'), {}, lab.initial())
        tree = calls[0][2]
        self.assertEqual({item['path'] for item in tree['tree']}, {'continuity/state.json', runtime.MEMORY_PATH})
        self.assertEqual(calls[1][2]['parents'], ['oldhead'])
        self.assertFalse(calls[2][2]['force'])
        state = json.loads(next(item['content'] for item in tree['tree'] if item['path'] == 'continuity/state.json'))
        self.assertEqual(state[runtime.ANCHOR], lab.digest(lab.initial()))

    def test_snapshot_verifies_anchor_and_source_bound_memory(self):
        api = runtime.ResearchGitHub()
        memory = lab.initial()
        raw = dict(head='head', state={runtime.ANCHOR: lab.digest(memory)})
        item = dict(content=base64.b64encode(lab.encode(memory).encode()).decode())
        with patch.object(api, 'raw_snapshot', return_value=raw), patch.object(api, 'call', return_value=item):
            self.assertEqual(api.snapshot()['memory'], memory)
            raw['state'][runtime.ANCHOR] = '0'*64
            with self.assertRaises(ValueError): api.snapshot()

    def test_only_404_is_missing_not_auth_failure(self):
        api = runtime.ResearchGitHub()
        for code in (404, 403):
            with patch.object(api, 'call', side_effect=HTTPError('url', code, 'error', None, None)):
                if code == 404:
                    self.assertFalse(api.memory_exists(dict(head='head')))
                else:
                    with self.assertRaises(HTTPError): api.memory_exists(dict(head='head'))

    def test_live_entry_rejects_nondefault_branch(self):
        with patch.dict(os.environ, {'GITHUB_REPOSITORY': host.REPO, 'GITHUB_REF': 'refs/heads/draft', 'GITHUB_EVENT_NAME': 'workflow_dispatch'}):
            with self.assertRaises(ValueError): runtime.main()

    def test_uninitialized_auto_uses_original_backend(self):
        original = object()
        with patch.dict(os.environ, {'GITHUB_REPOSITORY': host.REPO, 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'schedule', 'RESEARCH_MODE': 'auto', 'GITHUB_RUN_ID': '10', 'GITHUB_RUN_ATTEMPT': '1'}), \
            patch.object(sys, 'argv', ['runner', str(SOURCE)]), \
            patch.object(runtime.subprocess, 'check_output', return_value=host.SOURCE+'\n'), \
            patch.object(runtime.ResearchGitHub, 'raw_snapshot', return_value=dict(state={})), \
            patch.object(host, 'GitHub', return_value=original), \
            patch.object(host, 'run', return_value=dict(status='legacy')) as run, \
            patch('builtins.print'):
            runtime.main()
        self.assertIs(run.call_args.args[0], original)


if __name__ == '__main__':
    unittest.main()
