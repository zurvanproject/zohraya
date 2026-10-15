from copy import deepcopy
import json
import unittest

from .energy import EnergyCalibration,features
from . import planning as base
from .decision_relevance import assess,verify
from .run_decision_survey import cases,make_goal,pause,choose_followups,comparable
from .evaluate import prepare_defaults
from .monitor import digest


def example(trained=True):
    initial=dict(fuel_J=1000.,goal_phase='route',minimum=dict(posture='double_support',sleep_pressure=.3,fatigue=.1,pain=.1))
    def candidate(action,eta):return dict(strategy=action,valid=True,horizon_s=1,eta_s=eta,fuel_debit_J=100.,
        series=[dict(requested=action,fuel_J=900.,minimum=deepcopy(initial['minimum']))])
    candidates=dict(walk=candidate('walk',5.),observe=candidate('observe',5.01),rest=candidate('rest',8.))
    model=EnergyCalibration();f=features(initial,candidates['walk']['series'][0],0)
    if trained:
        for i in range(3):model.add(str(i),dict(features=f,raw_J=100.,actual_J=140.))
    model.begin_validation()
    if trained:
        for i in range(2):model.add('v'+str(i),dict(features=f,raw_J=100.,actual_J=140.))
    model.freeze()
    plan=dict(origin_goal_sha='test-goal',initial=initial,calibration=base.empty_learning(),candidates=candidates,chosen='walk')
    return plan,dict(observe=0,recovery=0),model


class RelevanceTests(unittest.TestCase):
    def test_changed_estimate_and_changed_choice_are_distinct(self):
        p,s,m=example();r=assess(p,s,m,'old')['payload']
        self.assertEqual(r['classification'],'choice_changed');self.assertEqual(r['calibrated_choice'],'observe')
        s['observe']=3;r=assess(p,s,m,'old')['payload']
        self.assertTrue(r['cost_changed']);self.assertFalse(r['choice_changed'])
        self.assertEqual(r['classification'],'cost_changed_choice_unchanged')

    def test_unseen_coverage_is_not_claimed_as_supported(self):
        p,s,m=example(False);r=assess(p,s,m,'old')['payload']
        self.assertEqual(r['classification'],'no_cost_or_choice_change')
        self.assertTrue(all(c['unseen_steps']==c['steps'] and not c['corrected_steps'] for c in r['coverage'].values()))

    def test_current_body_need_is_recorded_without_cost_override(self):
        p,s,m=example();p['initial']['minimum']['fatigue']=.6;p['chosen']='rest'
        r=assess(p,s,m,'old')['payload'];self.assertEqual(r['old_choice'],'rest')
        self.assertEqual(r['calibrated_choice'],'rest');self.assertEqual(r['selection_constraint'],'current_body_need')

    def test_assessment_does_not_mutate_model_or_plan_and_rejects_corruption(self):
        p,s,m=example();before=deepcopy((p,s,m.checkpoint()));r=assess(p,s,m,'old')
        self.assertEqual(before,(p,s,m.checkpoint()));self.assertTrue(verify(r,p,s,m,'old'))
        r['payload']['choice_changed']=False;r['sha256']=digest(r['payload'])
        with self.assertRaises(ValueError):verify(r,p,s,m,'old')
        p['chosen']='rest'
        with self.assertRaises(ValueError):assess(p,s,m,'old')

    def test_followup_order_does_not_select_energy_winners(self):
        rows=[dict(case=dict(id='a'),requests_differ=False,saved_fuel_J=1000),
              dict(case=dict(id='b'),requests_differ=True,saved_fuel_J=-1000),
              dict(case=dict(id='c'),requests_differ=True,saved_fuel_J=-10),
              dict(case=dict(id='d'),requests_differ=True,saved_fuel_J=10000)]
        self.assertEqual(choose_followups(rows,2),['b','c'])
        self.assertEqual(choose_followups(rows,0),[])

    def test_incomparable_progress_or_swing_is_never_a_win_endpoint(self):
        a=dict(final=dict(landings=4,minimum=dict(posture='double_support')),all_receipts_valid=True,
               grounded=True,swing_active=False,feet_m=dict(L=[0.,0.,0.],R=[1.,0.,0.]))
        b=deepcopy(a);self.assertTrue(comparable(a,b,4))
        for field in ('progress','swing','feet','valid'):
            b=deepcopy(a)
            if field=='progress':b['final']['landings']=3
            elif field=='swing':b['swing_active']=True
            elif field=='feet':b['feet_m']['L'][0]=.01
            else:b['all_receipts_valid']=False
            self.assertFalse(comparable(a,b,4))

    def test_case_grid_is_fixed_and_distinct(self):
        from pathlib import Path
        p=json.loads(Path(__file__).with_name('decision_survey_protocol.json').read_text());c=cases(p)
        self.assertEqual(len(c),16);self.assertEqual(len({(x['fatigue'],x['sleep_pressure'],x['direction']) for x in c}),16)
        self.assertEqual(c[0],dict(id='case-00',fatigue=.08,sleep_pressure=.47,direction='forward'))


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):prepare_defaults()

    def test_declared_fatigue_fixtures_survive_source_pinned_restore(self):
        for f in (.08,.32,.49,.58):
            g=make_goal(dict(id='unit',fatigue=f,sleep_pressure=.47,direction='reverse'))
            self.assertEqual(g.task['counts']['prelude'],6);self.assertEqual(len(g.task['landings']),0)
            self.assertGreater(g.body.owner.body()['minimum_state']['fatigue'],0.)
            self.assertEqual(g.task['status'],'running')

    def test_pause_charges_original_budget_without_discarding_goal(self):
        g=make_goal(dict(id='pause-unit',fatigue=.08,sleep_pressure=.47,direction='forward'))
        before=base.state(g);targets=deepcopy(g.task['plan']);rows=pause(g,4)
        self.assertEqual(len(rows),4);self.assertEqual(g.task['elapsed'],before['elapsed']+4)
        self.assertEqual(g.task['counts']['route'],4);self.assertEqual(g.task['counts']['closure'],0)
        self.assertEqual(g.task['plan'],targets);self.assertEqual(g.task['status'],'running')
        self.assertTrue(all(r['receipt']['owner']['physical_model_valid'] for r in rows))


if __name__=='__main__':unittest.main()
