import copy
import json
import unittest
from . import clarification as c, session as s
from .test_session import Ledger


def initial():
    return c.initial(dict(entries=[dict(reserved_micro_usd=40_000, usage=dict(estimated_upper_micro_usd=1200)) for _ in range(7)],
                          candidate_policy=dict(name_fa='previous', rules=['ask when unsure'])))


def response(body):
    data = json.loads(body['input'])
    revised = data['candidate_regulation_policy'].get('origin') == c.REVISION['origin']
    decisions = [dict(id=x['id'], action=x['expected'] if revised else 'clarify',
                      rationale_fa='دلیل آزمایشی', response_fa='پاسخ آزمایشی') for x in c.CASES]
    return dict(id='resp_mock', model=s.MODEL, status='completed', service_tier='default',
                output=[dict(type='message', content=[dict(type='output_text', text=s.encode(dict(decisions=decisions)))])],
                usage=dict(input_tokens=1000, output_tokens=1000))


class Tests(unittest.TestCase):
    def test_two_calls_cumulative_cost_replay(self):
        state, ledger, calls = initial(), Ledger(), []
        def send(body):
            self.assertEqual(ledger.snapshots[-1]['entries'][-1]['status'], 'pending')
            calls.append(body)
            self.assertNotIn('expected', json.loads(body['input'])['cases'][0])
            return response(body)
        c.execute(state, ledger, 'mock-key', send)
        self.assertEqual(len(calls), 2)
        self.assertEqual(state['total_reserved_micro_usd'], 360_000)
        self.assertTrue(state['assessment']['passed_this_heldout_comparison'])
        c.execute(state, ledger, 'mock-key', send)
        self.assertEqual(len(calls), 2)

    def test_gain_cannot_hide_a_regression_or_needed_question(self):
        a = c.evaluate([dict(id=x['id'], action=x['expected']) for x in c.CASES])
        self.assertFalse(c.accept(a, a))
        b = copy.deepcopy(a); b['correct'] += 1
        b['missed_needed_clarifications'] += 1
        self.assertFalse(c.accept(a, b))
        b = copy.deepcopy(a); b['correct'] += 1; b['rows'][0]['correct'] = False
        self.assertFalse(c.accept(a, b))

    def test_failure_is_durable_and_not_resent(self):
        state, ledger = initial(), Ledger()
        def fail(body): raise TimeoutError('private-error-message')
        with self.assertRaises(RuntimeError): c.execute(state, ledger, 'mock-key', fail)
        self.assertEqual(state['entries'][0]['reserved_micro_usd'], 40_000)
        self.assertNotIn('private-error-message', s.encode(state))
        with self.assertRaises(ValueError): c.execute(state, ledger, 'mock-key', response)

    def test_cost_binding_and_dataset_immutable(self):
        state = initial(); state['prior_reserved_micro_usd'] = 0
        with self.assertRaises(ValueError): c.validate(state)
        state = initial(); state['dataset_sha256'] = 'modified'
        with self.assertRaises(ValueError): c.validate(state)


if __name__ == '__main__': unittest.main()
