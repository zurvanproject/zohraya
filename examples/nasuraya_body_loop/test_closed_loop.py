"""Native tests for immutable evaluation policies and source-linked perturbations."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .host import BodyLoop
from .closed_loop import FrozenClosedLoop,validate_perturbation
from .adaptive_memory import initial_model
from .adaptive_memory import AdaptiveMemory
from .closed_loop_benchmark import fixture,start_from
from .self_maintenance import MaintenanceBlocked

CASE={'id':'unit-case','sleep_pressure':.2,'muscle_tone':.3,'warmup_walks':0,'perturbations':{}}
SOURCES=[{'origin':'unit test fixed persistence predictor; not learned parameters'}]


class ClosedLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'native.sqlite'
    def tearDown(self): self.temp.cleanup()
    def controller(self,loop,case=CASE):
        return FrozenClosedLoop(loop,model=initial_model(),sources=SOURCES,scenario=case)

    def test_three_actual_cycles_preserve_model_and_budget(self):
        with BodyLoop.start(self.path,max_actions=3) as loop:
            c=self.controller(loop);model=deepcopy(c.contract['model'])
            for _ in range(3): result=c.advance()
            self.assertEqual(result['status'],'completed')
            self.assertEqual(loop.status()['actions_remaining'],0)
            self.assertEqual(loop.status()['completed_cycles'],3)
            self.assertEqual(c.contract['model'],model)
            checkpoint=loop.observe()['checkpoint_sha256']
            self.assertEqual(result,c.advance())
            self.assertEqual(checkpoint,loop.observe()['checkpoint_sha256'])

    def test_budget_and_identity_are_existing_gates(self):
        with BodyLoop.start(self.path,max_actions=2) as loop:
            with self.assertRaises(MaintenanceBlocked): self.controller(loop)
        second=Path(self.temp.name)/'read.sqlite'
        with BodyLoop.start(second,max_actions=3,mode='observe') as loop:
            with self.assertRaises(MaintenanceBlocked): self.controller(loop)

    def test_native_perturbation_is_persisted_and_only_executed_once(self):
        case=deepcopy(CASE)
        case['perturbations']={'2':{'native':{'pain':[{'id':'test-pain','location':'forefoot_L','intensity':.8,
                                                   'quality':'pressure','cause':'unit synthetic fixture','duration_s':10.}]}}}
        with BodyLoop.start(self.path,max_actions=3) as loop:
            c=self.controller(loop,case);c.advance();c.advance();result=c.advance()
            self.assertEqual(result['status'],'blocked_physical_model')
            self.assertEqual(loop.status()['actions_remaining'],1)
            self.assertEqual(result['history'][1]['external'],case['perturbations']['2'])
            self.assertEqual(loop.engine.get('closed-unit-case-2')['request']['execution']['external'],case['perturbations']['2'])
            before=loop.status();self.assertEqual(result,c.advance());self.assertEqual(before,loop.status())

    def test_invalid_native_physics_cannot_train_adaptive_memory(self):
        from datetime import datetime,timedelta
        body=fixture(CASE)
        at=(datetime.fromisoformat(body.owner.wall_utc)+timedelta(seconds=.1)).isoformat()
        pain={'native':{'pain':[{'id':'preload-pain','location':'forefoot_L','intensity':.8,
                                'quality':'pressure','cause':'declared invalidity regression','duration_s':10.}]}}
        receipt=body.cycle(event_id='preload',at_utc=at,duration_s=.1,requested='observe',external=pain)
        self.assertFalse(receipt['owner']['physical_model_valid'])
        with start_from(self.path,body) as loop:
            m=AdaptiveMemory(loop)
            with self.assertRaisesRegex(MaintenanceBlocked,'physical model invalid'):
                m.execute('must-not-learn','observe')
            self.assertEqual(m.verify()[0],1)
            self.assertEqual(loop.status()['completed_cycles'],0)
            self.assertEqual(m.verify()[1],initial_model())
            with self.assertRaises(MaintenanceBlocked):m.execute('retry','observe')
            self.assertEqual(loop.status()['completed_cycles'],0)

    def test_invalid_physical_outcome_after_action_is_not_learned_or_replayed(self):
        pain={'native':{'pain':[{'id':'during-action','location':'forefoot_L','intensity':.8,
                                'quality':'pressure','cause':'declared outcome regression','duration_s':10.}]}}
        with BodyLoop.start(self.path,max_actions=3) as loop:
            m=AdaptiveMemory(loop)
            def disturbed_step(*,decision_id,duration_s,preferred_action):
                before=loop.observe()
                request=loop.make_request(decision_id,before,duration_s,preferred_action)
                record=loop.adapter.cycle(request,at_utc=request['at_utc'],duration_s=duration_s,external=pain)
                return loop.receipt(record,replayed=False)
            with patch.object(loop,'step',side_effect=disturbed_step):
                with self.assertRaisesRegex(MaintenanceBlocked,'not eligible for learning'):
                    m.execute('disturbed','observe')
            self.assertEqual(m.verify()[1],initial_model())
            self.assertEqual(loop.status()['completed_cycles'],1)
            with self.assertRaises(MaintenanceBlocked):m.execute('disturbed','observe')
            self.assertEqual(loop.status()['completed_cycles'],1)

    def test_unknown_outcome_blocks_new_action(self):
        with BodyLoop.start(self.path,max_actions=3) as loop:
            c=self.controller(loop)
            def stop(stage):
                if stage=='after_intent': raise RuntimeError('stopped before result')
            with self.assertRaises(RuntimeError): c.advance(fault=stop)
            with self.assertRaisesRegex(MaintenanceBlocked,'unknown'): c.advance()
            self.assertEqual(loop.status()['completed_cycles'],0)
            self.assertEqual(loop.status()['actions_remaining'],3)

    def test_real_process_stop_after_native_commit_recovers_without_replay(self):
        with BodyLoop.start(self.path,max_actions=3) as loop: self.controller(loop)
        code='''import os,sys
from examples.nasuraya_body_loop.host import BodyLoop
from examples.nasuraya_body_loop.closed_loop import FrozenClosedLoop
with BodyLoop(sys.argv[1]) as loop:
 def kill(stage):
  if stage=='after_native_commit': os._exit(73)
 FrozenClosedLoop(loop).advance(fault=kill)
'''
        p=subprocess.run([sys.executable,'-c',code,str(self.path)],capture_output=True,text=True,timeout=60)
        self.assertEqual(p.returncode,73,p.stdout+p.stderr)
        with BodyLoop(self.path) as loop:
            self.assertEqual(loop.status()['completed_cycles'],1)
            c=FrozenClosedLoop(loop);c.advance();result=c.advance()
            self.assertEqual(result['status'],'completed')
            self.assertEqual(loop.status()['completed_cycles'],3)
            self.assertEqual(loop.status()['actions_remaining'],0)

    def test_frozen_contract_tampering_fails_before_action(self):
        with BodyLoop.start(self.path,max_actions=3) as loop:
            c=self.controller(loop)
            loop.engine.db.execute("UPDATE nasu_frozen_contract SET record='{}'")
            with self.assertRaises(MaintenanceBlocked): c.advance()
            self.assertEqual(loop.status()['completed_cycles'],0)

    def test_result_corruption_blocks_continuation(self):
        with BodyLoop.start(self.path,max_actions=3) as loop:
            c=self.controller(loop);c.advance()
            loop.engine.db.execute("UPDATE nasu_frozen_steps SET result='{}'")
            with self.assertRaises(MaintenanceBlocked): c.advance()
            self.assertEqual(loop.status()['completed_cycles'],1)

    def test_external_change_to_body_is_not_silently_accepted(self):
        with BodyLoop.start(self.path,max_actions=3) as loop:
            c=self.controller(loop);c.advance()
            loop.observe();loop.step(decision_id='outsider',preferred_action='observe')
            with self.assertRaisesRegex(MaintenanceBlocked,'uncontracted'): c.advance()
            self.assertEqual(loop.status()['completed_cycles'],2)

    def test_perturbation_scope_refuses_tools_keys_and_nonfinite_values(self):
        for bad in [{'tool':'shell'},{'native':{'guardian':True}},{'native':{'unexpected_impulse_N_s':[float('nan'),0]}},
                    {'native':{'friction':{'L':-.1,'R':.1}}}]:
            with self.subTest(bad=bad),self.assertRaises(ValueError): validate_perturbation(bad)

    def test_changed_contract_reopen_is_rejected(self):
        with BodyLoop.start(self.path,max_actions=3) as loop:
            self.controller(loop)
            changed=deepcopy(CASE);changed['sleep_pressure']=.4
            with self.assertRaises(MaintenanceBlocked): self.controller(loop,changed)


if __name__=='__main__':unittest.main()
