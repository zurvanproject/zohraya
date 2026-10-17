"""Saved-goal continuation contracts; recorded complete fixture stays private."""
import json
import os
from pathlib import Path
import sys
import unittest
from copy import deepcopy

sys.path.insert(0,os.environ.get('NASURAYA_NATIVE_ROOT',str(Path(__file__).resolve().parents[2]/'runtimes/tadash_body')))
from unified_body_v2 import UnifiedBody
from extension_state import restore
from persistent_embodiment_v1 import digest
from motion_goal import MotionGoal


@unittest.skipUnless(os.environ.get('NASURAYA_CHAIN_SOURCE'),'external completed-route fixture required')
class GoalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=json.loads(Path(os.environ['NASURAYA_CHAIN_SOURCE']).read_text())

    def body(self):return restore(deepcopy(self.source))

    def test_new_goal_retains_native_stocks_time_history_and_previous_evidence(self):
        b=self.body();before=b.checkpoint();prior_cursor=deepcopy(b.owner.physical.star_started)
        g=MotionGoal.start(b,'reverse','test-retain')
        self.assertEqual(b.checkpoint(),before)
        self.assertEqual(g.task['prior_sha256'],self.source['sha256'])
        self.assertEqual(g.task['prior_cursor'],prior_cursor)
        self.assertEqual(g.task['counts'],dict(prelude=0,route=0,closure=0))
        self.assertEqual(b.owner.physical.star_started,dict(L=0,R=0))

    def test_incomplete_prior_goal_rejects_without_mutation(self):
        b=self.body();b.owner.physical.star_started['L']-=1
        before=b.checkpoint();cursor=deepcopy(b.owner.physical.star_started)
        with self.assertRaises(ValueError):MotionGoal.start(b,'reverse','test-reject')
        self.assertEqual(b.checkpoint(),before)
        self.assertEqual(b.owner.physical.star_started,cursor)

    def test_saved_tick_preserves_request_result_remaining_budget_and_charging(self):
        a=MotionGoal.start(self.body(),'reverse','test-cold')
        initial_time=a.body.owner.physical.state.time_s;fuel=a.body.owner.owner.body.state.fuel_J
        a.step();b=MotionGoal.restore(json.loads(json.dumps(a.checkpoint())))
        self.assertEqual(a.request(),b.request())
        ra=a.step();rb=b.step()
        self.assertEqual(ra,rb)
        self.assertEqual(a.checkpoint(),b.checkpoint())
        self.assertEqual(a.task['counts'],dict(prelude=2,route=0,closure=0))
        self.assertAlmostEqual(a.body.owner.physical.state.time_s-initial_time,2.)
        self.assertEqual(ra['owner_ticks'],10)
        self.assertGreater(fuel,a.body.owner.owner.body.state.fuel_J)

    def test_corrupt_budget_source_or_goal_checksum_rejects(self):
        g=MotionGoal.start(self.body(),'reverse','test-corrupt');saved=g.checkpoint()
        broken=deepcopy(saved);broken['payload']['task']['elapsed']=1
        with self.assertRaises(ValueError):MotionGoal.restore(broken)
        broken['sha256']=digest(broken['payload'])
        with self.assertRaises(ValueError):MotionGoal.restore(broken)
        broken=deepcopy(saved);broken['payload']['goal_source_sha256']='changed';broken['sha256']=digest(broken['payload'])
        with self.assertRaises(ValueError):MotionGoal.restore(broken)

    def test_high_sleep_veto_closes_incomplete_goal_without_forcing_walk(self):
        b=self.body();before=b.owner.body()
        b.owner.aux['sleep_pressure']=.95
        b.owner._record(before,b.owner.body(),'external_input',
            'declared synthetic high-sleep intervention on an isolated completed-route copy',0.)
        initial_time=b.owner.physical.state.time_s;walk_steps=b.owner.physical.state.walk_steps
        g=MotionGoal.start(b,'reverse','test-native-veto');selected=[]
        while g.task['status']=='running':
            r=g.step();selected.append(r['owner']['selected_action'])
        self.assertEqual(g.task['status'],'incomplete')
        self.assertEqual(g.task['stop_reason'],'three consecutive native vetoes')
        self.assertEqual(g.task['counts'],dict(prelude=6,route=3,closure=4))
        self.assertNotIn('walk',selected)
        self.assertEqual(b.owner.physical.state.walk_steps,walk_steps)
        self.assertAlmostEqual(b.owner.physical.state.time_s-initial_time,13.)


if __name__=='__main__':unittest.main()
