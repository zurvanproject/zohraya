from copy import deepcopy
import json
from pathlib import Path
import unittest

from .gate import claim, evaluate, finish, operator_contact

INITIAL = json.loads(Path(__file__).with_name('state.json').read_text())


class AbsenceTests(unittest.TestCase):
    def setUp(self):
        # Fixed fixture; the real control file is never modified by these tests.
        self.state = dict(INITIAL, enabled=True, last_contact_at='2026-10-16T13:52:23+03:30',
                          last_claimed_at=None, inflight_run_id=None, last_completed_run_id=None)

    def test_one_second_before_threshold_is_blocked(self):
        self.assertEqual(evaluate(self.state, '2026-10-17T13:52:22+03:30')['reason'], 'recent_contact')

    def test_exact_24_hours_is_eligible_in_both_timezones(self):
        self.assertTrue(evaluate(self.state, '2026-10-17T13:52:23+03:30')['eligible'])
        self.assertTrue(evaluate(self.state, '2026-10-17T10:22:23Z')['eligible'])

    def test_pause_wins_even_long_after_threshold(self):
        self.state['enabled'] = False
        self.assertEqual(evaluate(self.state, '2026-12-17T10:22:23Z')['reason'], 'paused')

    def test_claim_and_finish_do_not_mutate_caller(self):
        original = deepcopy(self.state)
        claimed = claim(self.state, '2026-10-17T10:22:23Z', 'absence_20261017')
        self.assertEqual(self.state, original)
        self.assertEqual(evaluate(claimed, '2026-10-19T10:22:23Z')['reason'], 'unresolved_previous_run')
        done = finish(claimed, '2026-10-17T10:32:23Z', 'absence_20261017')
        self.assertEqual(claimed['inflight_run_id'], 'absence_20261017')
        self.assertIsNone(done['inflight_run_id'])

    def test_completed_claim_still_consumes_rolling_daily_budget(self):
        state = claim(self.state, '2026-10-17T10:22:23Z', 'first')
        state = finish(state, '2026-10-17T10:23:23Z', 'first')
        self.assertEqual(evaluate(state, '2026-10-18T10:22:22Z')['reason'], 'daily_budget_used')
        self.assertTrue(evaluate(state, '2026-10-18T10:22:23Z')['eligible'])
        with self.assertRaises(ValueError): claim(state, '2026-10-18T10:22:23Z', 'first')

    def test_unresolved_effect_never_gets_an_automatic_retry(self):
        claimed = claim(self.state, '2026-10-17T10:22:23Z', 'unknown')
        with self.assertRaises(ValueError): claim(claimed, '2026-11-17T10:22:23Z', 'new')
        with self.assertRaises(ValueError): finish(claimed, '2026-10-17T10:32:23Z', 'wrong')

    def test_contact_defers_next_run_without_refunding_claim(self):
        claimed = claim(self.state, '2026-10-17T10:22:23Z', 'first')
        done = finish(claimed, '2026-10-17T10:23:23Z', 'first')
        contacted = operator_contact(done, '2026-10-18T09:00:00Z')
        self.assertEqual(evaluate(contacted, '2026-10-18T10:22:23Z')['reason'], 'recent_contact')
        self.assertEqual(contacted['last_claimed_at'], done['last_claimed_at'])

    def test_stop_command_state_pauses_without_clearing_inflight(self):
        state = claim(self.state, '2026-10-17T10:22:23Z', 'first')
        paused = operator_contact(state, '2026-10-17T10:23:23Z', pause=True)
        self.assertFalse(paused['enabled'])
        self.assertEqual(paused['inflight_run_id'], 'first')

    def test_bad_timestamp_future_clock_or_flag_fails_closed(self):
        for value in ['2026-10-17T13:52:23', 'broken', None, '2026-10-15T10:22:23Z']:
            self.assertFalse(evaluate(self.state, value)['eligible'])
        self.state['enabled'] = 'true'
        self.assertEqual(evaluate(self.state, '2026-10-17T10:22:23Z')['reason'], 'invalid_state')

    def test_missing_fields_bad_run_id_and_future_claim_are_rejected(self):
        del self.state['last_claimed_at']
        self.assertEqual(evaluate(self.state, '2026-10-17T10:22:23Z')['reason'], 'invalid_state')
        self.state['last_claimed_at'] = '2026-10-18T10:22:23Z'
        self.assertFalse(evaluate(self.state, '2026-10-17T10:22:23Z')['eligible'])
        self.state['last_claimed_at'] = None
        with self.assertRaises(ValueError): claim(self.state, '2026-10-17T10:22:23Z', '../bad')


if __name__ == '__main__':
    unittest.main()
