from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from .evaluate import fixture,prepare_defaults
from .regulation import RegulatedGoal,RegulationJournal,select,NoSafeChoice
from .monitor import digest
from extension_state import attach
from motion_goal import MotionGoal
from motion_journal import UnknownMotionOutcome
from unified_body_v2 import UnifiedBody
from coordinated_support import CoordinatedSupport


def knowledge():return dict(counts={},pending=[],episodes=0,last=None)


def choice_report(*,sleep=.3,fatigue=.1,context='new',uncertain=True):
    return dict(observed=dict(minimum=dict(sleep_pressure=sleep,fatigue=fatigue,pain=0.)),
        inferred=dict(context=context),recommendation='pause_and_observe' if uncertain else 'continue_with_native_guards')


def candidates(**actual):
    return {k:dict(valid=v is not None,actual=v,recovery_gain=.001) for k,v in actual.items()}


class SelectionTests(unittest.TestCase):
    def test_uncertainty_gets_one_observation_then_can_resume(self):
        r=choice_report();c=candidates(walk='walk',observe='observe',rest='rest')
        counts=dict(observe=0,recovery=0,walk=0,required=0)
        self.assertEqual(select('route',r,c,counts,[])[0],'observe')
        counts['observe']=1
        self.assertEqual(select('route',r,c,counts,['new'])[0],'walk')

    def test_current_need_can_choose_sleep_or_rest(self):
        counts=dict(observe=0,recovery=0,walk=0,required=0)
        self.assertEqual(select('route',choice_report(sleep=.95),candidates(walk='protect',observe='observe',sleep='sleep'),counts,[])[0],'sleep')
        self.assertEqual(select('route',choice_report(fatigue=.6),candidates(walk='protect',observe='observe',rest='rest'),counts,[])[0],'rest')

    def test_no_safe_candidate_is_not_forced_into_movement(self):
        with self.assertRaises(NoSafeChoice):
            select('route',choice_report(),candidates(walk=None,observe=None,rest=None),dict(observe=3,recovery=3),[])


class RegulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):prepare_defaults()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def goal(self,max_ticks=2,*,route=False,pressure=.3):
        body=fixture(pressure)
        attach(body,dict(star_enabled=False,star_started=dict(L=0,R=0),star_targets=dict(L=[],R=[]),cursor_semantics='confirmed'))
        original=MotionGoal.start(body,'reverse','reg-test')
        if route:
            for _ in range(6):original.step()
        return RegulatedGoal.start(original,knowledge(),session_id='test',max_ticks=max_ticks)

    def test_attach_preserves_original_goal_and_native_history(self):
        g=self.goal();self.assertEqual(g.goal.checkpoint()['sha256'],g.session['initial_goal_sha'])
        self.assertEqual(g.task['goal_id'],g.session['goal_id'])
        self.assertEqual(g.task['elapsed'],0)

    def test_counterfactuals_do_not_charge_owner(self):
        g=self.goal();before=g.body.checkpoint();request=g.request()
        self.assertEqual(g.body.checkpoint(),before)
        self.assertEqual(request['requested'],'slow_breath')
        expected=g._prepared['candidates']['slow_breath']['receipt_sha256'];r=g.step()
        self.assertEqual(digest(r),expected)
        self.assertEqual(g.task['elapsed'],1)
        self.assertEqual(g.session['records'][0]['decision']['goal_id'],g.task['goal_id'])

    def test_saved_session_restores_and_respects_its_budget(self):
        g=self.goal(max_ticks=1);g.step();saved=g.checkpoint()
        restored=RegulatedGoal.restore(json.loads(json.dumps(saved)))
        self.assertEqual(restored.checkpoint(),saved)
        self.assertEqual(restored.session['status'],'budget_exhausted')
        with self.assertRaises(ValueError):restored.step()

    def test_corrupt_decision_rejects_even_with_outer_checksum_repaired(self):
        g=self.goal();g.step();saved=g.checkpoint()
        saved['payload']['session']['records'][0]['decision']['reason']='invented'
        saved['sha256']=digest(saved['payload'])
        with self.assertRaises(ValueError):RegulatedGoal.restore(saved)

    def test_journal_commit_and_replay_use_one_owner_tick(self):
        g=self.goal();j=RegulationJournal.create(self.root/'body.sqlite',g)
        head=g.checkpoint()['sha256'];event=g.goal.request()['event_id']
        first=j.step(event_id=event,expected_head=head);after=j.load().checkpoint()
        self.assertEqual(j.step(event_id=event,expected_head=head),first)
        self.assertEqual(j.load().checkpoint(),after)

    def test_durable_outcome_recovery_uses_no_native_simulation(self):
        g=self.goal();j=RegulationJournal.create(self.root/'body.sqlite',g)
        def interrupt(stage,goal):
            if stage=='outcome_saved':raise RuntimeError('simulated process boundary')
        with self.assertRaises(RuntimeError):
            j.step(event_id=g.goal.request()['event_id'],expected_head=g.checkpoint()['sha256'],hook=interrupt)
        self.assertTrue(j.inspect()['durable_outcome'])
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('native replay')), \
             patch.object(CoordinatedSupport,'step',side_effect=AssertionError('preview replay')):
            r=j.recover()
        self.assertEqual(r['native_actions_executed'],0)
        self.assertEqual(j.load().task['elapsed'],1)

    def test_deliberate_observe_spends_route_time_but_is_not_a_walk_veto(self):
        g=self.goal(route=True);g.goal.task['vetoes']=2
        # Retain two actual-attempt vetoes across an intentional observation.
        g.session['initial_goal_sha']=g.goal.checkpoint()['sha256']
        before=g.task['elapsed'];r=g.step()
        self.assertEqual(g.session['records'][0]['decision']['request']['requested'],'observe')
        self.assertEqual(g.task['elapsed'],before+1)
        self.assertEqual(g.task['counts']['route'],1)
        self.assertEqual(g.task['vetoes'],2)
        self.assertEqual(g.task['phase'],'route')

    def test_real_high_sleep_recovery_stays_bounded_and_preserves_three_walk_vetoes(self):
        g=self.goal(max_ticks=12,route=True,pressure=.95)
        for _ in range(9):g.step()
        self.assertEqual(g.task['vetoes'],3)
        self.assertEqual(g.task['phase'],'closure')
        _,counts,_=g.derived()
        self.assertEqual(counts['recovery'],3)
        self.assertEqual(counts['observe'],3)
        self.assertEqual(counts['walk'],3)
        self.assertEqual(g.body.owner.physical.state.walk_steps,0)

    def test_cold_session_has_same_next_choice_and_owner_result(self):
        a=self.goal(route=True);a.step();b=RegulatedGoal.restore(json.loads(json.dumps(a.checkpoint())))
        self.assertEqual(a.request(),b.request())
        self.assertEqual(a.step(),b.step())
        self.assertEqual(a.checkpoint(),b.checkpoint())

    def test_unknown_executed_outcome_blocks_without_native_retry(self):
        g=self.goal();j=RegulationJournal.create(self.root/'body.sqlite',g)
        head=g.checkpoint()['sha256'];event=g.goal.request()['event_id']
        def interrupt(stage,goal):
            if stage=='executed':raise RuntimeError('outcome not durably recorded')
        with self.assertRaises(RuntimeError):
            j.step(event_id=event,expected_head=head,hook=interrupt)
        self.assertFalse(j.inspect()['durable_outcome'])
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('native retry')):
            with self.assertRaises(UnknownMotionOutcome):j.recover()
            with self.assertRaises(UnknownMotionOutcome):j.step(event_id=event,expected_head=head)
        self.assertEqual(j.inspect()['head'],head)
        self.assertEqual(j.inspect()['receipts'],0)


if __name__=='__main__':unittest.main()
