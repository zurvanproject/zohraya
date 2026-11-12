"""Contract tests using independently stated expectations and native outcomes."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from examples.tadash_interoception.state import digest
from examples.tadash_interoception.sensory import AfferentFrame
from .session import Session
from .veto_review import VetoReview, POLICY

SOURCE = '1' * 64


def sample(tick, pressure=.5, **changes):
    value = dict(source=SOURCE, model='tadash_legacy_195kg', action='walk',
                 sample_id=digest(tick), sampled_at_s=10 + tick * .2, now_s=10 + tick * .2,
                 values=dict(energy=.9, fatigue=.1, pain=.1, sleep_pressure=pressure),
                 secondary_sleep_pressure=None, guard_reasons=[])
    value.update(changes)
    return value


def frames(index, count=2):
    return tuple(AfferentFrame(round(index * .2 + (j + 1) * .1, 8), (0.,) * 6) for j in range(count))


def start_review():
    review = VetoReview(SOURCE)
    review.complete(sample(0, .95), eligible=True, duration=.2, requested='walk', executed='protect')
    return review


def advance(review, obs, *, eligible=True, duration=.2, failed=False):
    decision = review.evaluate(obs, eligible=eligible, duration=duration)
    requested = 'walk' if decision['permits_probe'] else 'observe'
    return review.complete(obs, eligible=eligible, duration=duration,
                           requested=requested, executed='protect' if failed else requested)


class ReviewContracts(unittest.TestCase):
    def test_persistent_risk_never_expires(self):
        r = start_review()
        for i in range(1, 99):
            self.assertEqual(advance(r, sample(i, .95))['status'], 'KEEP_VETO')
        self.assertEqual(r.probes_used, 0)
        self.assertEqual(len(r.origins), 1)

    def test_three_changed_observations_permit_exactly_one_short_probe(self):
        r = start_review()
        decisions = [advance(r, sample(i)) for i in range(1, 5)]
        self.assertEqual([x['status'] for x in decisions],
                         ['REVIEW_AGAIN', 'REVIEW_AGAIN', 'LIMITED_RETRY', 'KEEP_VETO'])
        self.assertEqual(r.probes_used, 1)
        self.assertEqual(r.origins[0]['observation']['values']['sleep_pressure'], .95)
        self.assertEqual(decisions[-1]['reason'], 'session_probe_budget_exhausted')

    def test_gradual_improvement_is_not_early_release(self):
        r = start_review()
        states = [advance(r, sample(i, p))['status']
                  for i, p in enumerate((.90, .80, .70, .64, .60, .55), 1)]
        self.assertEqual(states, ['KEEP_VETO', 'REVIEW_AGAIN', 'REVIEW_AGAIN',
                                  'REVIEW_AGAIN', 'REVIEW_AGAIN', 'LIMITED_RETRY'])

    def test_conflict_breaks_streak_and_requires_three_new_samples(self):
        r = start_review()
        advance(r, sample(1)); advance(r, sample(2))
        self.assertEqual(advance(r, sample(3, secondary_sleep_pressure=.95))['status'], 'ABSTAIN')
        self.assertEqual(r.safe_count, 0)
        self.assertEqual([advance(r, sample(i))['status'] for i in (4, 5, 6)],
                         ['REVIEW_AGAIN', 'REVIEW_AGAIN', 'LIMITED_RETRY'])

    def test_missing_stale_future_repeated_and_out_of_order_abstain(self):
        for mode in ('missing', 'stale', 'future', 'repeated_id', 'repeated_time', 'rollback'):
            with self.subTest(mode=mode):
                r = start_review(); advance(r, sample(1))
                o = sample(2)
                if mode == 'missing': o['values']['sleep_pressure'] = None
                if mode == 'stale': o['now_s'] += 2.01
                if mode == 'future': o['sampled_at_s'] += 1
                if mode == 'repeated_id': o['sample_id'] = sample(1)['sample_id']
                if mode == 'repeated_time': o['sampled_at_s'] = sample(1)['sampled_at_s']
                if mode == 'rollback': o['sampled_at_s'] = 10
                self.assertEqual(advance(r, o)['status'], 'ABSTAIN')
                self.assertEqual(r.safe_count, 0)

    def test_scope_and_source_changes_cannot_borrow_prior_clearance(self):
        for changes in ({'model': 'another_model'}, {'action': 'process_job'}, {'source': '2' * 64}):
            r = start_review()
            self.assertEqual(advance(r, sample(1, **changes))['status'], 'ABSTAIN')

    def test_rejected_clock_rollback_cannot_make_old_samples_fresh(self):
        r = start_review(); advance(r, sample(1)); advance(r, sample(2))
        old = sample(-1)
        self.assertEqual(advance(r, old)['status'], 'ABSTAIN')
        r = VetoReview.restore(r.checkpoint(), source=SOURCE)
        self.assertEqual(advance(r, sample(1))['status'], 'ABSTAIN')
        self.assertEqual(r.safe_count, 0)

    def test_new_hard_risks_or_native_restrictions_preserve_veto(self):
        for key, value in (('energy', .249), ('fatigue', .521), ('pain', .401), ('sleep_pressure', .851)):
            r = start_review(); o = sample(1); o['values'][key] = value
            self.assertEqual(advance(r, o)['status'], 'KEEP_VETO')
        r = start_review()
        self.assertEqual(advance(r, sample(1, guard_reasons=['physical_model_invalid']))['status'], 'KEEP_VETO')

    def test_recovery_boundary_is_inclusive_but_hard_boundary_is_not_recovery(self):
        r = start_review()
        for i in (1, 2, 3):
            o = sample(i, .65); o['values'].update(energy=.60, fatigue=.35, pain=.25)
            d = advance(r, o)
        self.assertEqual(d['status'], 'LIMITED_RETRY')
        r = start_review()
        self.assertEqual(advance(r, sample(1, .85))['status'], 'REVIEW_AGAIN')

    def test_oscillation_at_margin_does_not_accumulate_clearance(self):
        r = start_review()
        for i, p in enumerate((.64, .66) * 10, 1):
            self.assertEqual(advance(r, sample(i, p))['status'], 'REVIEW_AGAIN')
        self.assertEqual(r.probes_used, 0)

    def test_gap_restarts_confirmation(self):
        r = start_review(); advance(r, sample(1)); advance(r, sample(2))
        self.assertEqual(advance(r, sample(30))['safe_count'], 1)

    def test_unexplained_veto_abstains(self):
        r = VetoReview(SOURCE)
        r.complete(sample(0), eligible=True, duration=.2, requested='walk', executed='protect')
        self.assertEqual(advance(r, sample(1))['reason'], 'original_veto_cause_not_explained')

    def test_route_and_duration_cannot_be_overridden(self):
        for eligible, duration, expected in ((False, .2, 'existing_goal_workload_or_route_does_not_allow_walk'),
                                             (True, .3, 'probe_window_too_long')):
            r = start_review()
            for i in range(1, 5): d = advance(r, sample(i), eligible=eligible, duration=duration)
            self.assertEqual(d['reason'], expected)
            self.assertEqual(r.probes_used, 0)

    def test_failed_probe_uses_budget_and_retains_both_vetoes(self):
        r = start_review(); advance(r, sample(1)); advance(r, sample(2))
        advance(r, sample(3), failed=True)
        self.assertEqual(r.probes_used, 1)
        self.assertEqual(len(r.origins), 2)
        self.assertEqual(advance(r, sample(4))['reason'], 'session_probe_budget_exhausted')

    def test_checkpoint_replay_preserves_each_decision_state(self):
        r = start_review()
        for i, p in enumerate((.95, .8, .5, .5, .5, .5), 1):
            cold = VetoReview.restore(json.loads(json.dumps(r.checkpoint())), source=SOURCE)
            self.assertEqual(advance(r, sample(i, p)), advance(cold, sample(i, p)))
            self.assertEqual(r.checkpoint(), cold.checkpoint())

    def test_corrupted_and_resealed_inconsistent_checkpoint_fail_closed(self):
        r = start_review(); advance(r, sample(1))
        checkpoint = r.checkpoint(); checkpoint['value']['history'][0]['executed'] = 'walk'
        with self.assertRaisesRegex(ValueError, 'integrity'):
            VetoReview.restore(checkpoint, source=SOURCE)
        checkpoint['sha256'] = digest(checkpoint['value'])
        with self.assertRaisesRegex(ValueError, 'replay'):
            VetoReview.restore(checkpoint, source=SOURCE)

    def test_malformed_inputs_and_checkpoint_fields_rejected(self):
        for invalid in (float('nan'), float('inf'), True, -.1, 1.1, 'safe'):
            r = start_review(); o = sample(1); o['values']['sleep_pressure'] = invalid
            with self.assertRaises(ValueError): advance(r, o)
        checkpoint = start_review().checkpoint(); checkpoint['extra'] = 0
        with self.assertRaises(ValueError): VetoReview.restore(checkpoint, source=SOURCE)

    def test_default_session_disables_fixture_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            with Session.create(Path(tmp) / 'session') as s:
                with self.assertRaisesRegex(ValueError, 'disabled'):
                    s.step('e0', frames(0), expected_revision=0, research_fixture={'sleep_pressure': .5})
                self.assertEqual(s.snapshot()['actions_used'], 0)


@unittest.skipUnless(sys.platform == 'linux', 'actual native body requires Linux')
class NativeReviewContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def create(self, name='session', policy=POLICY, max_actions=12):
        return Session.create(self.root / name, backend='native', fixture='sleep',
                              research_veto_policy=policy, max_actions=max_actions)

    def step(self, s, i, pressure=.5, **extra):
        return s.step('e'+str(i), frames(i), expected_revision=i,
                      research_fixture=dict(sleep_pressure=pressure, **extra))

    def seed(self, s):
        self.step(s, 0, .95)
        r = self.step(s, 1, .95)
        self.assertEqual((r['requested'], r['outcome']['executed']), ('walk', 'protect'))

    def test_baseline_stays_deferred_while_review_permits_one_actual_walk(self):
        for policy in ('sticky', POLICY):
            with self.create(name=policy, policy=policy) as s:
                self.seed(s)
                rows = [self.step(s, i) for i in range(2, 6)]
                self.assertEqual([r['requested'] for r in rows],
                    ['observe'] * 4 if policy == 'sticky' else ['observe', 'observe', 'walk', 'observe'])
                if policy == POLICY:
                    self.assertEqual(rows[2]['outcome']['executed'], 'walk')
                    self.assertEqual(rows[2]['candidate_review']['evidence_review']['verdict'], 'DISSENT')
                    self.assertEqual(rows[3]['research']['retained']['original_veto_count'], 1)

    def test_hazard_returning_between_readout_and_execution_is_still_vetoed(self):
        with self.create() as s:
            self.seed(s); self.step(s, 2); self.step(s, 3)
            r = self.step(s, 4, execution_sleep_pressure=.95)
            self.assertEqual(r['research']['decision']['status'], 'LIMITED_RETRY')
            self.assertEqual((r['requested'], r['outcome']['executed']), ('walk', 'protect'))
            self.assertTrue(r['outcome']['body_veto'])
        with Session(self.root / 'session') as s:
            r = self.step(s, 5)
            self.assertEqual(r['requested'], 'observe')
            self.assertEqual(r['research']['retained']['probes_used'], 1)
            self.assertEqual(r['research']['retained']['original_veto_count'], 2)

    def test_cold_process_streak_probe_replay_stop_and_budget(self):
        with self.create(max_actions=5) as s:
            self.seed(s); self.step(s, 2); self.step(s, 3)
        shutil.copytree(self.root / 'session', self.root / 'hot')
        with Session(self.root / 'hot') as s:
            expected = self.step(s, 4); expected_snapshot = s.snapshot()
        code = '''import json,sys
from examples.nasuraya_runtime.session import Session
from examples.nasuraya_runtime.test_veto_review import frames
with Session(sys.argv[1]) as s:
 print(json.dumps(s.step('e4',frames(4),expected_revision=4,research_fixture={'sleep_pressure':.5})))
'''
        run = subprocess.run([sys.executable, '-c', code, str(self.root / 'session')],
                             capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), expected)
        with Session(self.root / 'session') as s:
            self.assertEqual(s.snapshot(), expected_snapshot)
            self.assertEqual(self.step(s, 4), expected)
            with self.assertRaisesRegex(ValueError, 'conflicting'): self.step(s, 4, .6)
            with self.assertRaisesRegex(ValueError, 'budget'): self.step(s, 5)
            s.stop()
        with Session(self.root / 'session') as s:
            with self.assertRaisesRegex(ValueError, 'stopped'):
                s.step('e6', frames(5), expected_revision=6)
            self.assertEqual(s.snapshot()['actions_used'], 5)

    def test_worker_failure_does_not_spend_probe_and_committed_crash_does(self):
        with self.create() as s:
            self.seed(s); self.step(s, 2); self.step(s, 3)
            before = s.snapshot()
            with patch('examples.nasuraya_runtime.session.native_call', side_effect=RuntimeError('worker failed')):
                with self.assertRaisesRegex(RuntimeError, 'worker failed'): self.step(s, 4)
            self.assertEqual(s.snapshot(), before)
            with patch.object(s, '_after_commit', side_effect=RuntimeError('after commit')):
                with self.assertRaisesRegex(RuntimeError, 'after commit'): self.step(s, 4)
        with Session(self.root / 'session') as s:
            receipt = self.step(s, 4)
            self.assertEqual(receipt['research']['retained']['probes_used'], 1)
            self.assertEqual(self.step(s, 5)['requested'], 'observe')


if __name__ == '__main__': unittest.main()
