"""Stage-3 loop admission and conservative replanning regressions.

These are intentionally independent of large native-model dependencies.
Full native evidence runs in the dedicated CI end-to-end step.
"""
import copy
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import stage3_cycle as cycle, goal_governor as governor


def valid_summary(rare=0):
    return {'validation_passed':True, 'cases':24, 'native_cycles':24,
            'slow_breath_events':rare,
            'exact_slow_breath_predictions':0,
            'exact_slow_breath_recall':0. if rare else None,
            'conclusion':'observed_taxonomy_limitation' if rare else 'no_slow_breath_in_challenge',
            'brier': .3,'pooled_brier':.4,'api_calls':0,
            'physical_actuator_calls':0,'learning_updates':0,'weights_unchanged':True}


class Stage3ReplanTests(unittest.TestCase):
    def test_rare_event_recommends_exact_taxonomy(self):
        plan = cycle.pick_next(valid_summary(3))
        self.assertEqual(plan['id'], 'test_five_class_action_taxonomy')
        self.assertFalse(plan['automatically_executed'])

    def test_missing_rare_event_does_not_claim_recall(self):
        plan=cycle.pick_next(valid_summary(0))
        self.assertEqual(plan['id'],'improve_rare_event_challenge')
        self.assertFalse(plan['automatically_executed'])

    def test_missing_or_failed_evidence_is_rejected(self):
        for change in ({'validation_passed':False},{'validation_passed':None},
                       {'cases':23},{'native_cycles':25},{'api_calls':1},
                       {'physical_actuator_calls':1},{'learning_updates':1},
                       {'weights_unchanged':False}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                cycle.pick_next(dict(valid_summary(),**change))

    def test_negative_nonfinite_or_mistyped_metrics_rejected(self):
        for field, value in [('brier',float('nan')),('pooled_brier',float('inf')),
                             ('brier',-1),('brier',3),('native_cycles',True),
                             ('slow_breath_events',True),('slow_breath_events',25),
                             ('slow_breath_events',-1)]:
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                cycle.pick_next(dict(valid_summary(),**{field:value}))

    def test_contradictory_rare_result_rejected(self):
        for change in ({'conclusion':'observed_taxonomy_limitation'},
                       {'exact_slow_breath_recall':0.0},
                       {'slow_breath_events':2}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                cycle.pick_next(dict(valid_summary(),**change))

    def test_contradictory_exact_label_claim_rejected(self):
        for change in ({'exact_slow_breath_predictions':1},
                       {'exact_slow_breath_recall':.7},
                       {'conclusion':'no_slow_breath_in_challenge'}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                cycle.pick_next(dict(valid_summary(2),**change))

    def test_proposal_must_match_verified_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace=Path(tmp)
            evidence={'run_id':'x','report_sha256':'a'*64,'delta':.1}
            decision=governor.propose(evidence)
            (workspace/'stage3-goal.json').write_text(governor.canonical(decision).decode())
            with patch.object(governor,'verified_network',return_value=evidence):
                checked, saved=cycle.checked_proposal(workspace,'x')
            self.assertEqual(checked,evidence)
            self.assertEqual(saved,decision)
            changed=dict(decision,decision_sha256='f'*64)
            (workspace/'stage3-goal.json').write_text(governor.canonical(changed).decode())
            with patch.object(governor,'verified_network',return_value=evidence):
                with self.assertRaisesRegex(ValueError,'decision'):
                    cycle.checked_proposal(workspace,'x')

    def test_not_allowed_goal_refuses_to_execute_before_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace=Path(tmp)/'work'
            workspace.mkdir()
            root=Path(tmp)/'repo';root.mkdir()
            other=workspace/'run'
            evidence={'run_id':'id','report_sha256':'a'*64,'delta':-.2}
            decision=governor.propose(evidence)
            (workspace/'stage3-goal.json').write_text(governor.canonical(decision).decode())
            with patch.object(governor,'verified_network',return_value=evidence):
                with self.assertRaisesRegex(ValueError,'explicitly allowed'):
                    cycle.run(workspace,'id',other,root=root)
            self.assertFalse(other.exists())

    def test_stop_blocks_before_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace=Path(tmp)/'work';workspace.mkdir()
            root=Path(tmp)/'repo';root.mkdir()
            (workspace/'STOP').touch()
            with self.assertRaisesRegex(RuntimeError,'stopped'):
                cycle.run(workspace,'id',workspace/'experiment',root=root)
            self.assertFalse((workspace/'experiment').exists())

    def test_output_cannot_be_inside_source_or_outside_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace=Path(tmp)/'work';workspace.mkdir()
            root=Path(tmp)/'source';root.mkdir()
            with self.assertRaisesRegex(ValueError,'outside source'):
                cycle.run(workspace,'id',root/'experiment',root=root)

    def test_receipts_dont_authorize_multiple_experiments(self):
        self.assertEqual(cycle.ALLOWED, {'rare_slow_breath'})
        self.assertLessEqual(cycle.MAX_WALL_SECONDS,130)

if __name__ == '__main__':
    unittest.main()
