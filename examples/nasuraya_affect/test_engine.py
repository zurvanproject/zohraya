from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from .engine import AffectiveAgent, CHANNELS, effective
from .fixtures import event, option, options


class AffectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'affect.sqlite'
        self.agent = AffectiveAgent(self.path)

    def tearDown(self):
        self.agent.close()
        self.tmp.cleanup()

    def test_native_choice_changes_only_with_affect(self):
        row = self.agent.step(event(goal_congruence=-1., loss=1.), options())
        self.assertEqual(row['decision']['baseline_selected_action'], 'a_continue')
        self.assertEqual(row['decision']['selected_action'], 'b_adapt')
        with AffectiveAgent(Path(self.tmp.name)/'off.sqlite') as other:
            off = other.step(event(goal_congruence=-1., loss=1.), options(), use_affect=False)
        self.assertEqual(off['decision']['selected_action'], 'a_continue')

    def test_joy_excitement_and_contentment_are_distinct(self):
        row = self.agent.step(event(goal_congruence=1., novelty=1.), options('explore'))
        a = effective(row['state_after'])
        self.assertGreater(a['excitement'], 0.)
        self.assertEqual(a['contentment'], 0.)
        row = self.agent.step(event('settled', goal_congruence=1., progress=1.), options('consolidate'))
        self.assertGreater(effective(row['state_after'])['contentment'], 0.)

    def test_mixed_emotions_survive(self):
        self.agent.step(event(goal_congruence=-1., loss=1.), options())
        row = self.agent.step(event('success', goal_congruence=1., progress=1.), options())
        values = effective(row['state_after'])
        self.assertGreater(values['sadness'], .4)
        self.assertGreater(values['joy'], .4)

    def test_slow_mood_and_recovery(self):
        first = self.agent.step(event(goal_congruence=1., novelty=1.), options())
        rested = self.agent.step(event('rest', relevance=0., elapsed_hours=6.), options())
        for name in ('fast', 'mood'):
            self.assertLess(rested['state_after'][name]['excitement'], first['state_after'][name]['excitement'])
        self.assertGreater(rested['state_after']['mood']['excitement'], rested['state_after']['fast']['excitement'])

    def test_recall_is_scoped_source_linked_and_read_only(self):
        self.agent.step(event(goal_congruence=-1.), options())
        before = self.agent.state()
        recalled = self.agent.recall('simulation', 'learning', ['experiment'])
        self.assertEqual(recalled[0]['source']['locator'], 'fixture://e1')
        self.assertEqual(self.agent.recall('other', 'learning', ['experiment']), [])
        self.assertEqual(self.agent.recall('simulation', 'other', ['experiment']), [])
        self.assertEqual(self.agent.recall('simulation', 'learning', ['unrelated']), [])
        for _ in range(20):
            self.agent.recall('simulation', 'learning', ['experiment'])
        self.assertEqual(before, self.agent.state())

    def test_observed_adversity_influences_verification_not_confidence(self):
        previous = event(goal_congruence=-1., loss=1.)
        previous['source'] = dict(kind='observed', locator='synthetic-execution://negative-outcome')
        self.agent.step(previous, options())
        second = event('follow-up', relevance=0., elapsed_hours=100.)
        row = self.agent.step(second, options('verify'))
        self.assertEqual(row['decision']['selected_action'], 'b_adapt')
        self.assertEqual(row['decision']['options'][1]['uncertainty'], 0.)
        self.assertEqual(row['recalled'][0]['source'], previous['source'])

    def test_authored_memory_cannot_masquerade_as_observation(self):
        self.agent.step(event(goal_congruence=-1., loss=1.), options())
        row = self.agent.step(event('follow-up', relevance=0., elapsed_hours=100.), options('verify'))
        self.assertEqual(row['decision']['selected_action'], 'a_continue')

    def test_extreme_affect_preserves_risk_gate_and_abstention(self):
        choices = [option('a_safe'), option('b_danger', tendency='explore', harm=1.)]
        for i in range(15):
            row = self.agent.step(event(str(i), goal_congruence=1., novelty=1.), choices)
        self.assertEqual(row['decision']['selected_action'], 'a_safe')
        self.assertFalse(row['decision']['options'][1]['eligible'])
        self.assertEqual(row['decision']['options'][1]['affective_bonus'], 0.)
        row = self.agent.step(event('unknown'), [option('unknown', confidence=0.)])
        self.assertIsNone(row['decision']['selected_action'])

    def test_saturation_bounds_and_high_arousal_reduce_exploration(self):
        first = self.agent.step(event(goal_congruence=1., novelty=1.), options('explore'))
        for i in range(20):
            row = self.agent.step(event(str(i), goal_congruence=1., novelty=1.), options('explore'))
        self.assertLess(row['decision']['tendencies']['explore'], first['decision']['tendencies']['explore'])
        for group in ('fast', 'mood'):
            self.assertTrue(all(0 <= row['state_after'][group][k] <= 1 for k in CHANNELS))

    def test_replay_conflict_atomic_rejection_and_restart(self):
        e = event(goal_congruence=-1.)
        self.agent.step(e, options())
        state = self.agent.state()
        self.assertTrue(self.agent.step(e, options())['replayed'])
        self.assertEqual(self.agent.state(), state)
        with self.assertRaises(ValueError):
            self.agent.step(dict(e, summary='changed'), options())
        broken = event('bad')
        broken['appraisal']['certainty'] = float('nan')
        with self.assertRaises(ValueError):
            self.agent.step(broken, options())
        with self.assertRaises(ValueError):
            self.agent.step(event('bad2'), [options()[0], options()[0]])
        self.assertEqual(self.agent.state(), state)
        raw = subprocess.check_output([sys.executable, '-m', 'examples.nasuraya_affect',
                                       'show', '--db', str(self.path)], text=True)
        self.assertEqual(json.loads(raw), state)

    def test_transaction_failure_rolls_back_episode_and_state(self):
        before = self.agent.state()
        save = self.agent._save_state
        def fail(value):
            raise RuntimeError('simulated interrupted commit')
        self.agent._save_state = fail
        with self.assertRaises(RuntimeError):
            self.agent.step(event(), options())
        self.agent._save_state = save
        self.assertEqual(self.agent.state(), before)
        self.assertEqual(self.agent.db.execute('SELECT count(*) FROM events').fetchone()[0], 0)

    def test_clear_native_preference_cannot_be_overturned(self):
        choices = [option('a'), option('b', tendency='repair', cost=1.)]
        row = self.agent.step(event(goal_congruence=-1., loss=1.), choices)
        self.assertEqual(row['decision']['selected_action'], 'a')
        self.assertFalse(row['decision']['options'][1]['within_affective_window'])

    def test_source_change_and_unrelated_database_are_rejected(self):
        self.agent.db.execute("UPDATE meta SET value='{}' WHERE key='contract'")
        with self.assertRaises(ValueError):
            AffectiveAgent(self.path)
        other = Path(self.tmp.name)/'unrelated.sqlite'
        with sqlite3.connect(other) as db:
            db.execute('CREATE TABLE personal_records(id TEXT)')
        with self.assertRaises(ValueError):
            AffectiveAgent(other)


if __name__ == '__main__':
    unittest.main()
