"""Native offline regression and real process interruption probes."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .host import BodyLoop
from .adaptive_memory import (AdaptiveMemory, FIELDS, ALPHA, DELTA_LIMIT, forecast,
                              initial_model, learn, state, validate_model, choose_action)
from .self_maintenance import IdentityContinuity, MaintenanceBlocked, PRINCIPLES


class AdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'body.sqlite'

    def tearDown(self):
        self.temp.cleanup()

    def test_verified_native_feedback_changes_parameters_and_reduces_next_error(self):
        with BodyLoop.start(self.path,max_actions=2) as loop:
            memory = AdaptiveMemory(loop)
            first = memory.execute('one','observe')
            self.assertTrue(first['learned'])
            v,model = memory.verify()
            self.assertEqual(v,2)
            self.assertTrue(any(x != 0 for b in model['buckets'].values() for x in b['delta'].values()))
            second = memory.execute('two','observe')
            self.assertLess(second['error']['mae'],first['error']['mae'])
            self.assertEqual(loop.status()['actions_remaining'],0)
        with BodyLoop(self.path) as loop:
            memory = AdaptiveMemory(loop)
            self.assertEqual(memory.verify()[0],3)
            self.assertEqual(memory.identity.verify()['principles'],list(PRINCIPLES))

    def test_static_arm_records_same_outcome_without_changing_parameters(self):
        with BodyLoop.start(self.path,max_actions=1) as loop:
            memory = AdaptiveMemory(loop,adaptive=False)
            memory.execute('one','observe')
            self.assertEqual(memory.verify()[1],initial_model())
            with self.assertRaises(MaintenanceBlocked): AdaptiveMemory(loop,adaptive=True)

    def test_complete_replay_is_exact_and_has_no_effect(self):
        with BodyLoop.start(self.path,max_actions=2) as loop:
            m = AdaptiveMemory(loop)
            original = m.execute('one','observe')
            checkpoint = loop.status()['self_model']['checkpoint_sha256']
            self.assertEqual(original,m.execute('one','observe'))
            self.assertEqual(checkpoint,loop.status()['self_model']['checkpoint_sha256'])
            self.assertEqual(m.verify()[0],2)
            self.assertEqual(loop.status()['actions_remaining'],1)
            with self.assertRaisesRegex(MaintenanceBlocked,'conflicting'): m.execute('one','walk')

    def kill_worker(self, stage):
        code = '''import os,sys
from examples.nasuraya_body_loop.host import BodyLoop
from examples.nasuraya_body_loop.adaptive_memory import AdaptiveMemory
with BodyLoop(sys.argv[1]) as loop:
 def stop(stage):
  if stage==sys.argv[2]: os._exit(73)
 AdaptiveMemory(loop).execute('killed','observe',fault=stop)
'''
        proc = subprocess.run([sys.executable,'-c',code,str(self.path),stage],capture_output=True,text=True,timeout=60)
        self.assertEqual(proc.returncode,73,proc.stderr+proc.stdout)

    def test_process_kill_during_learning_rolls_back_and_recovers_once(self):
        with BodyLoop.start(self.path,max_actions=2): pass
        self.kill_worker('during_learning')
        with BodyLoop(self.path) as loop:
            m = AdaptiveMemory(loop)
            self.assertEqual(m.verify()[0],1)
            self.assertEqual(loop.status()['completed_cycles'],1)
            m.reconcile()
            self.assertEqual(m.verify()[0],2)
            m.reconcile()
            self.assertEqual(m.verify()[0],2)
            self.assertEqual(loop.status()['completed_cycles'],1)
            self.assertEqual(loop.status()['actions_remaining'],1)

    def test_process_kill_after_body_commit_recovers_verified_outcome(self):
        with BodyLoop.start(self.path,max_actions=2): pass
        self.kill_worker('after_native_commit')
        with BodyLoop(self.path) as loop:
            m = AdaptiveMemory(loop)
            m.reconcile()
            self.assertEqual(m.verify()[0],2)
            self.assertEqual(loop.status()['completed_cycles'],1)
            self.assertEqual(m.execute('killed','observe')['model_after'],2)

    def test_process_kill_after_intent_never_reexecutes_unknown_action(self):
        with BodyLoop.start(self.path,max_actions=2): pass
        self.kill_worker('after_intent')
        with BodyLoop(self.path) as loop:
            m = AdaptiveMemory(loop)
            with self.assertRaisesRegex(MaintenanceBlocked,'unknown action'): m.execute('killed','observe')
            with self.assertRaises(MaintenanceBlocked): m.execute('new','observe')
            self.assertEqual(loop.status()['completed_cycles'],0)
            self.assertEqual(loop.status()['actions_remaining'],2)

    def test_outcome_supplied_by_caller_is_not_an_accepted_learning_interface(self):
        with BodyLoop.start(self.path,max_actions=1) as loop:
            m = AdaptiveMemory(loop)
            with self.assertRaises(TypeError): m.execute('fake','observe',verified=True)
            self.assertEqual(m.verify()[0],1)

    def test_damaged_model_and_deleted_history_fail_closed(self):
        with BodyLoop.start(self.path,max_actions=1) as loop:
            m = AdaptiveMemory(loop)
            loop.engine.db.execute("UPDATE nasu_predictor_versions SET record='not json'")
            with self.assertRaisesRegex(MaintenanceBlocked,'corrupt'): m.execute('one','observe')
            loop.engine.db.execute('DELETE FROM nasu_predictor_versions')
            with self.assertRaisesRegex(MaintenanceBlocked,'implicit reset'): AdaptiveMemory(loop)
            self.assertEqual(loop.status()['completed_cycles'],0)

    def test_damaged_experience_fail_closed(self):
        with BodyLoop.start(self.path,max_actions=2) as loop:
            m = AdaptiveMemory(loop)
            m.execute('one','observe')
            loop.engine.db.execute("UPDATE nasu_experiences SET result='{}'")
            with self.assertRaises(MaintenanceBlocked): m.execute('two','observe')
            self.assertEqual(loop.status()['completed_cycles'],1)

    def test_deleted_learning_provenance_blocks_further_action(self):
        with BodyLoop.start(self.path,max_actions=2) as loop:
            m = AdaptiveMemory(loop)
            m.execute('one','observe')
            loop.engine.db.execute('DELETE FROM nasu_experiences')
            with self.assertRaisesRegex(MaintenanceBlocked,'provenance'): m.execute('two','observe')
            self.assertEqual(loop.status()['completed_cycles'],1)

    def test_missing_and_out_of_range_inputs_cannot_produce_forecast(self):
        with BodyLoop.start(self.path,max_actions=1) as loop:
            m = AdaptiveMemory(loop)
            original = loop.observe()
            for f in FIELDS:
                for bad in [None,-.1,1.1,float('nan'),True]:
                    snapshot = deepcopy(original)
                    snapshot['minimum_state'][f] = bad
                    with self.subTest(f=f,bad=bad),self.assertRaises(ValueError): m.predict(snapshot,'walk')
            bad = deepcopy(original)
            del bad['minimum_state']['posture']
            with self.assertRaises(ValueError): m.predict(bad,'walk')

    def test_sudden_external_body_change_stops_next_action(self):
        with BodyLoop.start(self.path,max_actions=3) as loop:
            m = AdaptiveMemory(loop)
            m.execute('one','observe')
            loop.observe(); loop.step(decision_id='outside',preferred_action='observe')
            with self.assertRaisesRegex(MaintenanceBlocked,'changed outside'): m.execute('two','observe')
            self.assertEqual(loop.status()['completed_cycles'],2)

    def test_unseen_context_has_wide_uncertainty_and_goal_observes(self):
        with BodyLoop.start(self.path,max_actions=3) as loop:
            m = AdaptiveMemory(loop)
            p = m.predict(loop.observe(),'walk')
            self.assertTrue(p['uncertainty']['unseen_context'])
            self.assertEqual(set(p['uncertainty']['bounds'].values()),{1.})
            result = m.run_goal('cold',target_cycles=2)
            self.assertEqual([x['receipt']['requested_action'] for x in result['history']],['observe','observe'])
            self.assertEqual(result['status'],'completed')
            self.assertEqual(result,m.run_goal('cold',target_cycles=2))
            with self.assertRaisesRegex(MaintenanceBlocked,'goal contract'): m.run_goal('cold',target_cycles=3)

    def test_identity_and_local_model_reversions_are_versioned(self):
        with BodyLoop.start(self.path,max_actions=1) as loop:
            m = AdaptiveMemory(loop)
            m.execute('one','observe')
            self.assertEqual(m.revert_to(1,reason='reviewed local model correction'),3)
            self.assertEqual(m.verify()[1],initial_model())
            for key in ('principles','schema',*PRINCIPLES):
                with self.assertRaises(MaintenanceBlocked):
                    m.identity.revise_belief(key,False,reason='test forbidden learning change',evidence='fixture://identity/block')
            loop.engine.db.execute('DELETE FROM nasu_identity_versions')
            with self.assertRaises(MaintenanceBlocked): IdentityContinuity(loop.engine.db)

    def test_action_and_storage_authorization_is_fixed(self):
        with BodyLoop.start(self.path,mode='observe') as loop:
            m = AdaptiveMemory(loop)
            with self.assertRaises(ValueError): m.execute('bad','run')
            with self.assertRaises(MaintenanceBlocked): m.execute('one','observe')
            self.assertEqual(loop.status()['completed_cycles'],0)

    def test_goal_budget_exhaustion_persists_and_cannot_be_extended_by_replay(self):
        with BodyLoop.start(self.path,max_actions=1) as loop:
            m = AdaptiveMemory(loop)
            with self.assertRaisesRegex(MaintenanceBlocked,'budget'): m.run_goal('short',target_cycles=2)
            self.assertEqual(loop.status()['actions_remaining'],0)
            with self.assertRaises(MaintenanceBlocked): m.run_goal('short',target_cycles=2)
            self.assertEqual(loop.status()['completed_cycles'],1)

    def test_goal_time_budget_prevents_new_action(self):
        with BodyLoop.start(self.path,max_actions=1) as loop:
            m = AdaptiveMemory(loop)
            with patch('examples.nasuraya_body_loop.adaptive_memory.time.monotonic',side_effect=[0.,2.]):
                result = m.run_goal('time',target_cycles=1,time_budget_s=1.)
            self.assertEqual(result['status'],'time_budget_exhausted')
            self.assertEqual(loop.status()['completed_cycles'],0)

    def test_repeated_prediction_failures_trigger_explicit_guard(self):
        with BodyLoop.start(self.path,max_actions=1) as loop:
            before = loop.observe()
            model = initial_model()
            for _ in range(3):
                p = forecast(model,before,'walk',1)
                after = deepcopy(before)
                # Pure synthetic adversarial unit fixture, never accepted by native memory.
                after['minimum_state']['energy'] = 0.
                after['minimum_state']['balance'] = 0.
                model,error = learn(model,before,p,{'self_model_after':after,'actual_action':'protect'})
                self.assertGreater(error['mae'],.05)
            self.assertEqual(model['failure_streak'],3)
            self.assertTrue(all(abs(d)<=DELTA_LIMIT for b in model['buckets'].values() for d in b['delta'].values()))
            bad = deepcopy(model); bad['alpha']=.9
            with self.assertRaises(MaintenanceBlocked): validate_model(bad)
            for item in model['buckets'].values():
                item['delta'] = {f:0. for f in FIELDS}
                item['residual_bound'] = {f:.005 for f in FIELDS}
                item['outcomes'] = {'walk':item['count']}
            self.assertEqual(choose_action(model,before,1),'observe')
            model['failure_streak']=0
            self.assertEqual(choose_action(model,before,1),'walk')
            for item in model['buckets'].values(): item['residual_bound']['energy']=0.
            with self.assertRaises(MaintenanceBlocked): validate_model(model)

    def test_sleep_guard_and_actual_body_veto_are_retained(self):
        with BodyLoop.start(self.path,fixture='sleep',max_actions=2) as loop:
            m = AdaptiveMemory(loop)
            first = m.execute('explicit-stress','walk')
            self.assertEqual(first['receipt']['actual_action'],'protect')
            result = m.run_goal('safe',target_cycles=1)
            self.assertEqual(result['history'][0]['receipt']['requested_action'],'observe')
            self.assertEqual(result['history'][0]['receipt']['actual_action'],'observe')


if __name__ == '__main__': unittest.main()
