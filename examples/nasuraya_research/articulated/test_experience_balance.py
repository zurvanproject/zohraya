"""Selection/measurement contracts; actual physics outcomes live in evidence."""
from copy import deepcopy
import unittest
from .experience_balance import frozen_plan,select_policy
from .experience_context import choose,select_memory
from .stepping import walk_trial


def records(plan):
    out=[]
    for bias in plan['candidates_m']:
        for case in plan['training']:
            out.append(dict(case=deepcopy(case),bias_m=bias,split='train',result=dict(
                walk_pass=True,accepted_steps=2,final_max_generalized_speed=.001,
                tilt_rms_deg=1.,simulated_seconds=17.)))
    return out


class ExperienceBalanceTests(unittest.TestCase):
    def test_selection_uses_measured_training_improvement_and_survives_serialization(self):
        import json
        plan=frozen_plan();rows=records(plan)
        for row in rows:
            if row['bias_m']==.003:row['result']['tilt_rms_deg']=.8
        policy=select_policy(plan,rows)
        self.assertEqual(policy['selected_bias_m'],.003)
        self.assertEqual(select_policy(plan,json.loads(json.dumps(rows))),policy)
        self.assertIs(policy['native_apply_allowed'],False)

    def test_failure_or_extra_wait_cannot_win_by_lowering_error(self):
        plan=frozen_plan()
        for change in ('walk_pass','duration'):
            rows=records(plan)
            for row in rows:
                if row['bias_m']==.006:
                    row['result']['tilt_rms_deg']=.01
                    if change=='walk_pass':row['result']['walk_pass']=False
                    else:row['result']['simulated_seconds']=18.
            self.assertEqual(select_policy(plan,rows)['selected_bias_m'],0.)

    def test_tiny_change_keeps_zero_offset(self):
        plan=frozen_plan();rows=records(plan)
        for row in rows:
            if row['bias_m']==.003:row['result']['tilt_rms_deg']=.99
        self.assertEqual(select_policy(plan,rows)['selected_bias_m'],0.)

    def test_holdouts_missing_duplicate_and_changed_scenarios_are_rejected(self):
        plan=frozen_plan()
        for bad in ('holdout','missing','duplicate','scenario'):
            rows=records(plan)
            if bad=='holdout':rows[0]['split']='holdout'
            elif bad=='missing':rows.pop()
            elif bad=='duplicate':rows.append(deepcopy(rows[0]))
            else:rows[0]['case']['friction']=.9
            with self.subTest(bad=bad),self.assertRaises(ValueError):select_policy(plan,rows)

    def test_parameters_cannot_relax_geometry_or_checkpoint_gates(self):
        for value in (True,float('nan'),float('inf'),.02,-.02,'0'):
            with self.subTest(value=value),self.assertRaises(ValueError):walk_trial(com_bias_x_m=value)
        with self.assertRaises(ValueError):walk_trial(com_bias_x_m=.003)
        with self.assertRaises(ValueError):
            walk_trial(com_bias_x_m=.003,geometry_support=True,retain_checkpoint=True)

    def test_context_memory_keeps_baseline_where_training_does_not_improve(self):
        plan=frozen_plan();rows=records(plan)
        for row in rows:
            if row['bias_m']==.006:
                row['result']['tilt_rms_deg']=.8 if row['case']['friction']>=.55 else 1.2
        memory=select_memory(plan,rows)
        self.assertEqual(choose(memory,.4),0.)
        self.assertEqual(choose(memory,.5),0.)
        self.assertEqual(choose(memory,.58),.006)
        self.assertEqual(choose(memory,.8),.006)

    def test_context_rejects_contaminated_training_and_unknown_friction(self):
        plan=frozen_plan();rows=records(plan);rows[0]['split']='holdout'
        with self.assertRaises(ValueError):select_memory(plan,rows)
        memory=select_memory(plan,records(plan))
        for value in (True,0.,-.1,float('nan'),float('inf'),'0.6'):
            with self.subTest(value=value),self.assertRaises(ValueError):choose(memory,value)


if __name__=='__main__':unittest.main()
