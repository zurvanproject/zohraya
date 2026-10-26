from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .evaluate import fixture,prepare_defaults
from .planning import (PlanningGoal,PlanningJournal,empty_learning,choose,score,
                       feedback,learn,advance_motion,NoSafeChoice)
from .monitor import digest
from .test_regulation import knowledge
from extension_state import attach
from motion_goal import MotionGoal
from motion_journal import UnknownMotionOutcome
from unified_body_v2 import UnifiedBody


def minimum(**updates):
    m=dict(sleep_pressure=.3,fatigue=.1,pain=.1,posture='double_support');m.update(updates);return m


def candidate(action,eta=5.,fuel=500.,valid=True):
    return dict(strategy=action,eta_s=eta,horizon_s=5,valid=valid,fuel_debit_J=fuel,
        series=[dict(requested=action,minimum=minimum())])


class SelectionTests(unittest.TestCase):
    def test_learned_cost_changes_next_selection(self):
        c=dict(walk=candidate('walk',eta=5.),observe=candidate('observe',eta=5.2))
        base=empty_learning();spent=dict(observe=0,recovery=0)
        self.assertEqual(choose('route',minimum(),c,base,spent)[0],'walk')
        # Deliberately constructed forecast error, not a private-body result.
        row=dict(decision=dict(request=dict(requested='walk')),feedback=dict(
            fuel_error_J=400.,fatigue_error=0.,settled_eta_errors=[dict(strategy='walk',error_s=4.)]))
        trained=learn(base,row)
        self.assertEqual(choose('route',minimum(),c,trained,spent)[0],'observe')
        self.assertEqual(base,empty_learning())

    def test_observation_not_inserted_during_swing(self):
        c=dict(walk=candidate('walk',eta=5.),observe=candidate('observe',eta=1.))
        self.assertEqual(choose('route',minimum(posture='walk_swing'),c,empty_learning(),dict(observe=0,recovery=0))[0],'walk')

    def test_current_need_and_remaining_recovery_budget(self):
        c=dict(walk=candidate('walk'),sleep=candidate('sleep',eta=12.))
        self.assertEqual(choose('route',minimum(sleep_pressure=.95),c,empty_learning(),dict(observe=0,recovery=0))[0],'sleep')
        self.assertEqual(choose('route',minimum(sleep_pressure=.95),c,empty_learning(),dict(observe=0,recovery=3))[0],'walk')

    def test_invalid_candidates_never_forced(self):
        with self.assertRaises(NoSafeChoice):
            choose('route',minimum(),dict(walk=candidate('walk',valid=False)),empty_learning(),dict(observe=0,recovery=0))


class PlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):prepare_defaults()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def goal(self,pressure=.3):
        b=fixture(pressure);attach(b,dict(star_enabled=False,star_started=dict(L=0,R=0),star_targets=dict(L=[],R=[]),cursor_semantics='confirmed'))
        g=MotionGoal.start(b,'reverse','planning-test')
        for _ in range(6):g.step()
        return PlanningGoal.start(g,knowledge(),session_id='planning-test')

    def test_shared_advance_matches_original_walk_exactly(self):
        a=self.goal().goal;b=deepcopy(a)
        self.assertEqual(a.step(),advance_motion(b,b.request()))
        self.assertEqual(a.checkpoint(),b.checkpoint())

    def test_multitick_forecasts_do_not_charge_owner(self):
        p=self.goal();before=p.goal.checkpoint();d=p.prepare()
        self.assertEqual(p.goal.checkpoint(),before)
        self.assertGreater(len(d['plan']['candidates']['walk']['series']),1)
        self.assertLessEqual(len(d['plan']['candidates']['walk']['series']),16)
        self.assertEqual(p.session['max_ticks'],224)

    def test_cold_restored_plan_has_same_next_action_and_effect(self):
        a=self.goal();a.step();b=PlanningGoal.restore(json.loads(json.dumps(a.checkpoint())))
        with patch('examples.nasuraya_self_model.planning.rollout',side_effect=AssertionError('unneeded replan')):
            self.assertEqual(a.request(),b.request())
            self.assertEqual(a.step(),b.step())
        self.assertEqual(a.checkpoint(),b.checkpoint())

    def test_feedback_and_budget_corruption_rejected(self):
        p=self.goal();p.step();saved=p.checkpoint()
        for field in ['feedback','budget']:
            bad=deepcopy(saved)
            if field=='feedback':bad['payload']['session']['records'][0]['feedback']['fuel_error_J']+=1.
            else:bad['payload']['session']['max_ticks']+=1
            bad['sha256']=digest(bad['payload'])
            with self.assertRaises(ValueError):PlanningGoal.restore(bad)

    def test_durable_outcome_recovers_without_forecast_or_execution(self):
        p=self.goal();j=PlanningJournal.create(self.root/'journal.sqlite',p);head=p.checkpoint()['sha256'];event=p.goal.request()['event_id']
        def crash(stage,goal):
            if stage=='outcome_saved':raise RuntimeError('fault injection')
        with self.assertRaises(RuntimeError):j.step(event_id=event,expected_head=head,hook=crash,current_goal=p)
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('native replay')), \
             patch('examples.nasuraya_self_model.planning.rollout',side_effect=AssertionError('forecast replay')):
            result=j.recover()
        self.assertEqual(result['native_actions_executed'],0)
        self.assertEqual(j.load().task['elapsed'],7)

    def test_unknown_result_blocks_retry_even_with_cached_goal(self):
        p=self.goal();j=PlanningJournal.create(self.root/'journal.sqlite',p);head=p.checkpoint()['sha256'];event=p.goal.request()['event_id']
        def crash(stage,goal):
            if stage=='executed':raise RuntimeError('lost result')
        with self.assertRaises(RuntimeError):j.step(event_id=event,expected_head=head,hook=crash,current_goal=p)
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('native retry')):
            with self.assertRaises(UnknownMotionOutcome):j.recover()
            with self.assertRaises(UnknownMotionOutcome):j.step(event_id=event,expected_head=head,current_goal=p)

    def test_cached_owner_matches_default_and_stale_cache_rejects(self):
        p=self.goal();old=p.checkpoint();a=PlanningJournal.create(self.root/'a.sqlite',p)
        b=PlanningJournal.create(self.root/'b.sqlite',PlanningGoal.restore(old))
        event=p.goal.request()['event_id'];head=old['sha256']
        r=a.step(event_id=event,expected_head=head,current_goal=p)
        self.assertEqual(r,b.step(event_id=event,expected_head=head))
        self.assertEqual(p.checkpoint(),b.load().checkpoint())
        self.assertEqual(a.step(event_id=event,expected_head=head,current_goal=p),r)
        with self.assertRaises(ValueError):
            a.step(event_id=p.goal.request()['event_id'],expected_head=p.checkpoint()['sha256'],current_goal=PlanningGoal.restore(old))

    def test_three_native_vetoes_still_close_route(self):
        p=self.goal(.95)
        for _ in range(12):
            if p.task['phase']!='route':break
            p.step()
        self.assertEqual(p.task['phase'],'closure')
        self.assertEqual(p.task['vetoes'],3)
        self.assertEqual(len(p.task['landings']),0)

    def test_earlier_eta_forecasts_settle_only_when_landing_is_observed(self):
        # Synthetic delayed observation, including an expired earlier forecast.
        m=minimum();initial=dict(time_s=0.,fuel_J=1000.,minimum=m,landings=0)
        def decision(origin,time):
            c=candidate('walk',eta=1.);c['series']=[dict(requested='walk',time_s=time+1.,fuel_J=900.,minimum=m,landings=1)]
            p=dict(origin_goal_sha=origin,initial={**initial,'time_s':time},candidates=dict(walk=c),chosen='walk',calibration=empty_learning())
            return dict(plan=p,offset=0,request=dict(requested='walk'),before={**initial,'time_s':time})
        old=dict(decision=decision('early',0.))
        row=dict(decision=decision('late',2.),after=dict(time_s=3.,last_landing_t_s=2.5,fuel_J=900.,minimum=m,landings=1),
                 receipt=dict(owner=dict(selected_action='walk')))
        f=feedback(row,empty_learning(),[old])
        self.assertEqual([x['error_s'] for x in f['settled_eta_errors']],[1.5,-.5])
        row['after']['landings']=0
        self.assertEqual(feedback(row,empty_learning(),[old])['settled_eta_errors'],[])


if __name__=='__main__':unittest.main()
