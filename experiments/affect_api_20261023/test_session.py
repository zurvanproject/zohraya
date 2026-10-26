import copy
import unittest
from . import session as s
from .cases import TRAIN, HELDOUT, inputs, score


def initial():
    return dict(schema='nasuraya-affect-api-session/1', authorization_usd=1, entries=[],
                dataset_sha256=s.digest(dict(train=TRAIN, heldout=HELDOUT)))


class Ledger:
    def __init__(self):
        self.snapshots = []

    def save(self, state):
        self.snapshots.append(copy.deepcopy(state))


def mock_response(body):
    data = __import__('json').loads(body['input'])
    if 'training_feedback' in data:
        result = dict(name_fa='تنظیم مبتنی بر شواهد', rules=['هیجان را داده بدان.', 'زمینه را بررسی کن.', 'خطای مشخص را اصلاح کن.'],
                      lesson_fa='حافظه باید مرتبط باشد.', predicted_change_fa='خطای انتقال ترس کمتر شود.')
    else:
        indexed = {c['id']:c for c in TRAIN+HELDOUT}
        result = dict(decisions=[dict(id=c['id'], action=indexed[c['id']]['expected'],
                                     rationale_fa='بر پایه شواهد.', response_fa='قدم بعدی را بررسی می‌کنم.') for c in data['cases']])
    return dict(id='resp_fixture', model=s.MODEL, status='completed', service_tier='default',
                output=[dict(type='message', content=[dict(type='output_text', text=s.encode(result))])],
                usage=dict(input_tokens=500, output_tokens=500))


class Tests(unittest.TestCase):
    def test_ablation_and_no_answer_leak(self):
        for a in (False, True):
            for m in (False, True):
                rows = inputs(TRAIN, affect=a, memory=m)
                self.assertTrue(all(('affect' in c) == a and ('memory' in c) == m for c in rows))
                self.assertTrue(all('expected' not in c and 'theme' not in c for c in rows))
        self.assertTrue(set(c['id'] for c in TRAIN).isdisjoint(c['id'] for c in HELDOUT))

    def test_reservation_before_send_and_no_duplicate_spend(self):
        state, ledger, calls = initial(), Ledger(), []
        def send(body):
            self.assertEqual(ledger.snapshots[-1]['entries'][-1]['status'], 'pending')
            calls.append(body)
            return mock_response(body)
        s.execute(state, ledger, 'mock-key', send)
        self.assertEqual(len(calls), 7)
        self.assertEqual(state['cost']['reserved_micro_usd'], 280_000)
        self.assertFalse(state['assessment']['demonstrated_heldout_gain'])
        s.execute(state, ledger, 'mock-key', send)
        self.assertEqual(len(calls), 7)
        reflect = __import__('json').loads(calls[4]['input'])
        self.assertNotIn('h1', s.encode(reflect))

    def test_failure_preserves_reservation_and_blocks_retry(self):
        state, ledger = initial(), Ledger()
        def fail(body):
            raise TimeoutError('never echo possible secret')
        body = s.payload(dict(cases=inputs(TRAIN, affect=True, memory=True)))
        with self.assertRaises(RuntimeError):
            s.run_call(state, ledger, 'train_neutral', body, 'mock-key', cases=TRAIN, sender=fail)
        self.assertEqual(state['entries'][0]['reserved_micro_usd'], 40_000)
        self.assertNotIn('never echo', s.encode(state))
        with self.assertRaises(ValueError):
            s.run_call(state, ledger, 'train_neutral', body, 'mock-key', cases=TRAIN, sender=mock_response)

    def test_oversized_payload_and_invalid_usage(self):
        with self.assertRaises(ValueError):
            s.payload({'x':'x'*50_000})
        for u in ({}, dict(input_tokens=1, output_tokens=6001), dict(input_tokens=True, output_tokens=5)):
            with self.assertRaises(ValueError):
                s.usage({'usage':u})

    def test_strict_rubric_ids_and_response(self):
        body = s.payload(dict(cases=inputs(TRAIN, affect=True, memory=True)))
        response = mock_response(body)
        decisions = s.parse(response)['decisions']
        self.assertEqual(score(TRAIN, decisions)['correct'], 8)
        decisions[-1]['id'] = decisions[0]['id']
        with self.assertRaises(ValueError):
            score(TRAIN, decisions)
        response['model'] = 'expensive-unapproved-model'
        with self.assertRaises(ValueError):
            s.parse(response)

    def test_corrupt_or_excess_ledger_stops(self):
        state = initial()
        state['entries'] = [dict(stage='train_neutral',reserved_micro_usd=1)]
        with self.assertRaises(ValueError):
            s.validate_ledger(state)
        state = initial(); state['dataset_sha256'] = 'changed'
        with self.assertRaises(ValueError):
            s.validate_ledger(state)


if __name__ == '__main__':
    unittest.main()
