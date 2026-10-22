"""Offline tests. The provider is a test double, never a live model."""
from copy import deepcopy
from datetime import timedelta
import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from continuity_host import model_research as model, research_lab as lab, host

spec = importlib.util.spec_from_file_location('model_test_gate', Path(os.environ.get('NASURAYA_TEST_SOURCE', 'source'))/'continuity/gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
NOW = '2026-10-23T01:00:00+00:00'
CONTACT = '2026-10-21T00:00:00+00:00'


def response(feature='freshness'):
    proposal = dict(feature=feature, question='Will this rule reduce recall errors?',
                    rationale='The measured training errors motivate testing this feature.',
                    prediction='The relevant synthetic error category should decrease.',
                    reflection='Previous measured outcomes, not confidence, determine retention.')
    return dict(id='resp_offline_test_double', status='completed', model=model.MODEL,
                usage=dict(input_tokens=1200, output_tokens=600),
                output=[dict(type='reasoning', summary=[]), dict(type='message', role='assistant',
                    content=[dict(type='output_text', text=lab.encode(proposal))])])


class Fake:
    def __init__(self, seed=None):
        self.memory = model.initial(seed)
        self.state = dict(schema=gate.SCHEMA, enabled=True, last_contact_at=CONTACT,
                          last_claimed_at=None, inflight_run_id=None, last_completed_run_id=None,
                          **{model.ANCHOR: lab.digest(self.memory)})
        self.head = 'head_0'
        self.saved = []
        self.conflict = False
        self.pause_after_claim = False
        self.orphan = False
        self.seed = seed

    def raw_snapshot(self):
        if self.pause_after_claim and self.saved:
            self.state['enabled'] = False
        return dict(head=self.head, tree='tree', state=deepcopy(self.state))

    def read_optional(self, snapshot, path):
        if path == model.MEMORY_PATH:
            return deepcopy(self.memory) if model.ANCHOR in self.state or self.orphan else None
        return deepcopy(self.seed)

    def snapshot(self):
        snapshot = self.raw_snapshot()
        model.validate(self.memory)
        if self.state.get(model.ANCHOR) != lab.digest(self.memory):
            raise ValueError('anchor mismatch')
        snapshot['memory'] = deepcopy(self.memory)
        return snapshot

    def save_model(self, snapshot, state, memory, report=None):
        if self.conflict or snapshot['head'] != self.head:
            raise RuntimeError('CAS conflict')
        model.validate(memory)
        self.memory = deepcopy(memory)
        self.state = deepcopy(state)
        self.state[model.ANCHOR] = lab.digest(memory)
        self.saved.append(deepcopy(report))
        self.head = 'head_'+str(len(self.saved))
        return self.head


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.api = Fake()
        self.clock = patch.object(host, 'now', return_value=NOW)
        self.clock.start(); self.addCleanup(self.clock.stop)

    def run_job(self, execute=None, run_id='gh_123_1'):
        return model.run(self.api, gate, run_id, execute or (lambda body: response()))

    def test_reservation_is_durable_before_network(self):
        def provider(body):
            self.assertEqual(self.api.state['inflight_run_id'], 'gh_123_1')
            self.assertEqual(self.api.memory['entries'][0]['reserved_micro_usd'], 20000)
            self.assertEqual(self.api.memory['entries'][0]['status'], 'pending')
            return response()
        result = self.run_job(provider)
        self.assertTrue(result['model_api_used'])
        self.assertTrue(result['memory_updated'])
        self.assertEqual(len(self.api.saved), 2)
        self.assertLess(result['usage']['estimated_upper_micro_usd'], model.RESERVE)

    def test_real_model_choice_not_offline_fixed_choice(self):
        result = self.run_job(lambda body: response('context'))
        self.assertTrue(result['memory_updated'])
        self.assertTrue(self.api.memory['policy']['context'])
        self.assertFalse(self.api.memory['policy']['freshness'])

    def test_four_calls_resume_and_stop(self):
        for i, feature in enumerate(lab.FEATURES):
            at = (model.stamp(NOW)+timedelta(days=i)).isoformat()
            with patch.object(host, 'now', return_value=at):
                self.run_job(lambda body, f=feature: response(f), 'gh_'+str(200+i)+'_1')
            self.api.memory = json.loads(lab.encode(self.api.memory))
            model.validate(self.api.memory)
        with patch.object(host, 'now', return_value='2026-10-27T01:00:00+00:00'):
            result = self.run_job(lambda body: self.fail('extra paid call'), 'gh_999_1')
        self.assertEqual(result['status'], 'curriculum_complete')
        self.assertEqual(sum(e['reserved_micro_usd'] for e in self.api.memory['entries']), 80000)

    def test_timeout_keeps_reservation_and_inflight(self):
        def provider(body):
            raise TimeoutError('outcome unknown')
        with self.assertRaises(TimeoutError): self.run_job(provider)
        self.assertEqual(self.api.memory['entries'][0]['status'], 'pending')
        self.assertEqual(self.api.state['inflight_run_id'], 'gh_123_1')
        self.assertEqual(self.run_job()['reason'], 'unresolved_previous_run')

    def test_missing_key_never_claims(self):
        with patch.dict(os.environ, {}, clear=True):
            result = model.run(self.api, gate, 'gh_123_1')
        self.assertEqual(result['reason'], 'missing_secure_api_key')
        self.assertEqual(self.api.saved, [])

    def test_paused_never_claims(self):
        self.api.state['enabled'] = False
        self.assertEqual(self.run_job()['reason'], 'paused')
        self.assertEqual(self.api.saved, [])

    def test_daily_execution_gate_stays_shared(self):
        self.run_job()
        self.assertEqual(self.run_job()['reason'], 'daily_budget_used')
        self.assertEqual(gate.evaluate(self.api.state, NOW)['reason'], 'daily_budget_used')

    def test_claim_conflict_never_sends(self):
        self.api.conflict = True
        with self.assertRaises(RuntimeError):
            self.run_job(lambda body: self.fail('unclaimed paid call'))
        self.assertEqual(self.api.memory['entries'], [])

    def test_contact_during_call_does_not_apply(self):
        def provider(body):
            self.api.state['last_contact_at'] = NOW
            return response()
        result = self.run_job(provider)
        self.assertFalse(result['memory_updated'])
        self.assertEqual(self.api.memory['policy'], lab.BASELINE)
        self.assertEqual(self.api.memory['entries'][0]['reserved_micro_usd'], model.RESERVE)

    def test_pause_before_send_cancels_without_refund(self):
        self.api.pause_after_claim = True
        result = self.run_job(lambda body: self.fail('paused paid call'))
        self.assertFalse(result['model_api_used'])
        self.assertEqual(self.api.memory['entries'][0]['status'], 'cancelled_before_send')
        self.assertEqual(self.api.memory['entries'][0]['reserved_micro_usd'], model.RESERVE)

    def test_failed_final_commit_retains_pending_claim(self):
        def provider(body):
            self.api.conflict = True
            return response()
        with self.assertRaises(RuntimeError): self.run_job(provider)
        self.assertEqual(self.api.memory['entries'][0]['status'], 'pending')
        self.assertIsNotNone(self.api.state['inflight_run_id'])

    def test_incomplete_response_is_not_retried(self):
        calls = []
        def provider(body):
            calls.append(body)
            return dict(response(), status='incomplete')
        with self.assertRaises(ValueError): self.run_job(provider)
        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(self.api.state['inflight_run_id'])

    def test_missing_usage_is_not_invented(self):
        with self.assertRaises(ValueError): self.run_job(lambda body: dict(response(), usage={}))
        self.assertEqual(self.api.memory['entries'][0]['status'], 'pending')

    def test_refusal_does_not_become_an_experiment(self):
        data = response()
        data['output'][-1]['content'] = [dict(type='refusal', refusal='No')]
        with self.assertRaises(ValueError): self.run_job(lambda body: data)
        self.assertEqual(self.api.memory['policy'], lab.BASELINE)

    def test_model_cannot_request_other_actions(self):
        data = response()
        text = json.loads(data['output'][-1]['content'][0]['text'])
        text['shell_command'] = 'do not execute'
        data['output'][-1]['content'][0]['text'] = json.dumps(text)
        with self.assertRaises(ValueError): self.run_job(lambda body: data)

    def test_unexpected_model_is_not_accepted(self):
        with self.assertRaises(ValueError): self.run_job(lambda body: dict(response(), model='expensive-model'))

    def test_token_overrun_stops(self):
        data = response(); data['usage']['output_tokens'] = model.MAX_OUTPUT_TOKENS+1
        with self.assertRaises(ValueError): self.run_job(lambda body: data)

    def test_pricing_expiration_stops_before_claim(self):
        with patch.object(host, 'now', return_value=model.PRICE_EXPIRES):
            with self.assertRaises(ValueError): self.run_job()
        self.assertEqual(self.api.saved, [])

    def test_tampered_experiment_rejected(self):
        self.run_job()
        self.api.memory['entries'][0]['trial']['validation']['after']['errors'] = 0
        with self.assertRaises(ValueError): model.validate(self.api.memory)

    def test_tampered_budget_rejected(self):
        self.run_job()
        self.api.memory['entries'][0]['reserved_micro_usd'] = 0
        with self.assertRaises(ValueError): model.validate(self.api.memory)

    def test_policy_without_evidence_rejected(self):
        self.api.memory['policy']['trusted'] = True
        with self.assertRaises(ValueError): model.validate(self.api.memory)

    def test_duplicate_request_refused(self):
        self.run_job()
        with self.assertRaises(ValueError): model.check_budget(self.api.memory, NOW, 'gh_123_1')

    def test_failed_validation_preserves_incumbent(self):
        real = lab.evaluate
        def worse(policy, rows):
            result = real(policy, rows)
            if len(rows) == 288 and policy['freshness']:
                result['errors'] = 288; result['by_kind']['clean'] = 48
            return result
        with patch.object(lab, 'evaluate', side_effect=worse):
            self.assertFalse(self.run_job()['memory_updated'])
        self.assertEqual(self.api.memory['policy'], lab.BASELINE)

    def test_prompt_has_no_credentials_tools_or_validation_rows(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-secret-not-real', 'GH_HOST_TOKEN': 'test-github-not-real'}):
            body = model.payload(self.api.memory)
        encoded = lab.encode(body)
        self.assertNotIn('test-secret-not-real', encoded)
        self.assertNotIn('test-github-not-real', encoded)
        self.assertNotIn('tools', body)
        self.assertFalse(body['store'])
        self.assertEqual(body['max_output_tokens'], 4096)
        self.assertNotIn('validation', json.loads(body['input']))

    def test_previous_measurements_reach_next_prompt(self):
        self.run_job()
        data = json.loads(model.payload(self.api.memory)['input'])
        self.assertEqual(data['previous_measured_outcomes'][0]['feature'], 'freshness')
        self.assertNotIn('freshness', data['allowed_features'])

    def test_cold_process_validates_memory_without_api(self):
        self.run_job()
        code = 'import json,sys; from continuity_host.model_research import validate; validate(json.load(sys.stdin)); print("valid")'
        child = subprocess.run([sys.executable, '-c', code], input=lab.encode(self.api.memory),
                               text=True, capture_output=True, timeout=10,
                               env={'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.strip(), 'valid')

    def test_budget_lifetime_cap_without_reset(self):
        memory = model.initial()
        for index in range(model.MAX_CALLS):
            at = (model.stamp(NOW)+timedelta(days=index)).isoformat()
            memory['entries'].append(dict(run_id=f'gh_{500+index}_1', at=at,
                reserved_micro_usd=model.RESERVE, request_sha256='0'*64,
                status='cancelled_before_send', proposal=None, trial=None,
                applied=False, usage=None, response_id=None))
        with self.assertRaisesRegex(ValueError, 'financial cap'):
            model.check_budget(memory, '2026-11-05T01:00:00+00:00', 'gh_999_1')

    def test_rolling_daily_cap(self):
        memory = model.initial()
        for index in range(2):
            memory['entries'].append(dict(run_id=f'gh_{500+index}_1', at=NOW,
                reserved_micro_usd=model.RESERVE, request_sha256='0'*64,
                status='cancelled_before_send', proposal=None, trial=None,
                applied=False, usage=None, response_id=None))
        with self.assertRaisesRegex(ValueError, 'financial cap'):
            model.check_budget(memory, NOW, 'gh_999_1')

    def test_initialize_preserves_existing_execution_budget_and_pause(self):
        del self.api.state[model.ANCHOR]
        self.api.state['enabled'] = False
        self.api.state['last_claimed_at'] = CONTACT
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-placeholder'}):
            result = model.initialize(self.api, gate)
        self.assertFalse(result['model_api_used'])
        self.assertFalse(self.api.state['enabled'])
        self.assertEqual(self.api.state['last_claimed_at'], CONTACT)

    def test_initialization_refuses_reinitialization_and_orphan(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-placeholder'}):
            with self.assertRaises(ValueError): model.initialize(self.api, gate)
            del self.api.state[model.ANCHOR]
            self.api.orphan = True
            with self.assertRaises(ValueError): model.initialize(self.api, gate)

    def test_imports_existing_research_without_repeating_completed_features(self):
        seed, _ = lab.advance(lab.initial(), 'prior_offline')
        memory = model.initial(seed)
        model.validate(memory)
        self.assertTrue(memory['policy']['freshness'])
        self.assertNotIn('freshness', model.available(memory))


class TransportAndStorageTests(unittest.TestCase):
    def test_transport_is_single_post_and_secrets_only_in_header(self):
        class Reply:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return lab.encode(response()).encode()
        from unittest.mock import MagicMock
        opener = MagicMock(); opener.open.return_value = Reply()
        body = model.payload(model.initial())
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-placeholder'}), patch.object(model, 'build_opener', return_value=opener):
            self.assertEqual(model.call_model(body)['status'], 'completed')
        self.assertEqual(opener.open.call_count, 1)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, model.ENDPOINT)
        self.assertNotIn(b'offline-placeholder', request.data)
        self.assertEqual(request.get_method(), 'POST')

    def test_surrounding_whitespace_is_removed_from_api_key(self):
        class Reply:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return lab.encode(response()).encode()
        from unittest.mock import MagicMock
        opener = MagicMock(); opener.open.return_value = Reply()
        raw_key = '  \\n\\t offline-placeholder \\r\\n  '.replace('\\n', '\n').replace('\\r', '\r').replace('\\t', '\t')
        with patch.dict(os.environ, {'OPENAI_API_KEY': raw_key}), patch.object(model, 'build_opener', return_value=opener):
            self.assertEqual(model.call_model(model.payload(model.initial()))['status'], 'completed')
        headers = dict(opener.open.call_args.args[0].header_items())
        self.assertEqual(headers['Authorization'], 'Bearer offline-placeholder')
        self.assertEqual(opener.open.call_count, 1)

    def test_internal_whitespace_in_key_fails_before_network(self):
        from unittest.mock import MagicMock
        opener = MagicMock()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'invalid internal\\nkey'.replace('\\n', '\n')}), patch.object(model, 'build_opener', return_value=opener):
            with self.assertRaisesRegex(ValueError, 'invalid API key format'):
                model.call_model(model.payload(model.initial()))
        opener.open.assert_not_called()

    def test_transport_error_sanitized_and_no_retry(self):
        from unittest.mock import MagicMock
        opener = MagicMock(); opener.open.side_effect = RuntimeError('secret-in-exception')
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-placeholder'}), patch.object(model, 'build_opener', return_value=opener):
            with self.assertRaises(RuntimeError) as caught:
                model.call_model(model.payload(model.initial()))
        self.assertNotIn('secret-in-exception', str(caught.exception))
        self.assertEqual(opener.open.call_count, 1)

    def test_redirect_refused(self):
        with self.assertRaises(RuntimeError):
            model.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid')

    def test_storage_uses_atomic_tree_and_nonforce_ref(self):
        api = model.ModelGitHub(); calls = []
        def call(method, path, data=None):
            calls.append((method, path, data))
            return {'sha': 'tree' if path == 'git/trees' else 'commit'}
        with patch.object(api, 'call', side_effect=call):
            api.save_model(dict(head='old', tree='oldtree'), {}, model.initial())
        self.assertEqual({e['path'] for e in calls[0][2]['tree']}, {'continuity/state.json', model.MEMORY_PATH})
        self.assertEqual(calls[1][2]['parents'], ['old'])
        self.assertFalse(calls[2][2]['force'])

    def test_storage_auth_error_is_not_missing_memory(self):
        api = model.ModelGitHub()
        with patch.object(api, 'call', side_effect=HTTPError('url', 403, 'denied', {}, None)):
            with self.assertRaises(HTTPError): api.read_optional({'head': 'head'}, model.MEMORY_PATH)
        with patch.object(api, 'call', side_effect=HTTPError('url', 404, 'missing', {}, None)):
            self.assertIsNone(api.read_optional({'head': 'head'}, model.MEMORY_PATH))

    def test_snapshot_verifies_anchor(self):
        api = model.ModelGitHub(); memory = model.initial()
        raw = dict(head='head', state={model.ANCHOR: lab.digest(memory)})
        with patch.object(api, 'raw_snapshot', return_value=raw), patch.object(api, 'read_optional', return_value=memory):
            self.assertEqual(api.snapshot()['memory'], memory)
            raw['state'][model.ANCHOR] = '0'*64
            with self.assertRaises(ValueError): api.snapshot()


if __name__ == '__main__':
    unittest.main(verbosity=2)
