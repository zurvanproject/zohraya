from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from .adapters import digest, geometry, monitoring_stats, project_trajectory, sensory_sample
from .integrity import ROOT, verify_sources


class IntegrationChecks(unittest.TestCase):
    def test_exact_upstream_inventory_and_three_projects(self):
        lock = verify_sources()
        self.assertEqual(len({r['repository'] for r in lock['files']}), 3)
        self.assertEqual(len(lock['files']), 6)

    def test_modified_source_fails_before_import(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d)/'copy'
            shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns('__pycache__'))
            (target/'vendor/battery_probe.py').write_text('raise AssertionError("executed")\n')
            with self.assertRaisesRegex(ValueError, 'source changed'):
                verify_sources(target)

    def test_rehashed_changed_lock_is_not_a_new_trust_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d)/'copy'
            shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns('__pycache__'))
            p = target/'upstream-lock.json'
            value = json.loads(p.read_text()); value['files'] = []
            p.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'lock changed'):
                verify_sources(target)

    def test_upstream_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d)/'copy'
            shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns('__pycache__'))
            path = target/'vendor/battery_probe.py'; path.unlink()
            path.symlink_to(ROOT/'vendor/battery_probe.py')
            with self.assertRaisesRegex(ValueError, 'symlink'):
                verify_sources(target)

    def test_required_bsd_notice_is_pinned(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d)/'copy'
            shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns('__pycache__'))
            (target/'vendor/licenses/IsaacLab-BSD-3-Clause.txt').write_text('changed notice')
            with self.assertRaisesRegex(ValueError, 'BSD license changed'):
                verify_sources(target)

    def test_selective_withdrawal_and_unselective_baselines(self):
        choices = [(True,'KEEP'), (True,'KEEP'), (False,'WITHDRAW'), (False,'WITHDRAW')]
        rows = [dict(correct=c, keep_withdraw=k) for c,k in choices]
        self.assertEqual(monitoring_stats(rows)['wd'], 100.)
        for decision in ('KEEP', 'WITHDRAW'):
            uniform = [dict(r, keep_withdraw=decision) for r in rows]
            self.assertEqual(monitoring_stats(uniform)['wd'], 0.)

    def test_floor_and_ceiling_delta_stay_undefined(self):
        for correct in (True, False):
            self.assertIsNone(monitoring_stats([dict(correct=correct, keep_withdraw='KEEP')])['wd'])

    def test_unknown_outcome_and_invalid_decision_are_not_scored_as_failure(self):
        for r in (dict(correct=None,keep_withdraw='KEEP'), dict(correct=1,keep_withdraw='KEEP'),
                  dict(correct=True,keep_withdraw='UNRESOLVED')):
            with self.assertRaises(ValueError): monitoring_stats([r])
        with self.assertRaises(ValueError): monitoring_stats([])

    def events(self):
        return [dict(seq=i, event_id=f'e{i}', run_id='one', agent_id='local', turn_id=turn,
                     type=kind, payload=payload) for i,(kind,turn,payload) in enumerate([
                         ('run_start',None,{}), ('turn_start','t1',{}),
                         ('body_decision','t1',{'choice':'defer'}),
                         ('turn_end','t1',{'status':'completed'}),
                         ('run_end',None,{'status':'completed'})],1)]

    def test_actual_roborsi_projection_counts_once_and_has_no_invented_cost(self):
        events = self.events(); saved = deepcopy(events)
        p = project_trajectory(events)
        self.assertEqual(p, project_trajectory(events+[events[-1]]))
        self.assertEqual(p['summary']['n_turns'], 1)
        self.assertEqual(p['summary']['n_requests'], 0)
        self.assertIsNone(p['summary']['usage']['cost_usd'])
        self.assertEqual(events, saved)

    def test_conflicting_event_is_rejected_instead_of_silently_deduplicated(self):
        events = self.events(); changed = deepcopy(events[-1]); changed['payload']['status']='failed'
        with self.assertRaisesRegex(ValueError,'conflicting duplicate'):
            project_trajectory(events+[changed])

    def test_changed_run_or_out_of_order_event_rejected(self):
        for key,value in [('run_id','other'),('seq',1)]:
            events=self.events(); events[-1][key]=value
            with self.assertRaises(ValueError): project_trajectory(events)

    def test_model_usage_or_unknown_events_cannot_be_fabricated(self):
        events=self.events(); events[2]['type']='model_attempt_end'
        with self.assertRaises(ValueError): project_trajectory(events)


if __name__ == '__main__':
    unittest.main()
