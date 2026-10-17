import copy
import importlib.util
from pathlib import Path
import os
import subprocess
import unittest
from unittest.mock import patch
from continuity_host import host

SOURCE = Path(os.environ.get('NASURAYA_TEST_SOURCE','source')).resolve()
spec = importlib.util.spec_from_file_location('pinned_gate',SOURCE/'continuity/gate.py')
gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
START='2026-10-16T10:00:00Z'; DUE='2026-10-17T10:00:00Z'


class Fake:
    def __init__(self):
        self.state=dict(schema=gate.SCHEMA,enabled=True,last_contact_at=START,
            last_claimed_at=None,inflight_run_id=None,last_completed_run_id=None)
        self.head='initial'; self.saved=[]; self.conflict=False; self.pause=False
    def snapshot(self):
        if self.pause and self.saved: self.state['enabled']=False
        return dict(head=self.head,state=copy.deepcopy(self.state))
    def save(self,snapshot,state,report=None):
        if self.conflict or snapshot['head']!=self.head: raise RuntimeError('CAS conflict')
        self.state=copy.deepcopy(state); self.head='commit'+str(len(self.saved))
        self.saved.append(copy.deepcopy(report)); return self.head


class HostTests(unittest.TestCase):
    def setUp(self): self.api=Fake(); self.clock=patch.object(host,'now',return_value=DUE);self.clock.start();self.addCleanup(self.clock.stop)
    def run_job(self,execute=lambda _:dict(passed=True)): return host.run(self.api,gate,SOURCE,'gh_123_1',execute)
    def test_claim_precedes_work_and_daily_replay_defers(self):
        def work(_):
            self.assertEqual(self.api.state['inflight_run_id'],'gh_123_1'); return dict(passed=True)
        self.assertEqual(self.run_job(work)['status'],'recorded')
        self.assertEqual(self.run_job()['reason'],'daily_budget_used')
        self.assertEqual(len(self.api.saved),2)
    def test_claim_conflict_never_executes(self):
        self.api.conflict=True
        with self.assertRaises(RuntimeError): self.run_job(lambda _:self.fail('unclaimed work'))
    def test_unknown_outcome_keeps_inflight(self):
        def crash(_): raise OSError('lost worker')
        with self.assertRaises(OSError): self.run_job(crash)
        self.assertEqual(self.run_job()['reason'],'unresolved_previous_run')
    def test_recent_contact_and_pause_defer(self):
        self.api.state['last_contact_at']=DUE
        self.assertEqual(self.run_job()['reason'],'recent_contact')
        self.api.state['enabled']=False
        self.assertEqual(self.run_job()['reason'],'paused')
    def test_pause_after_claim_cancels_and_stays_paused(self):
        self.api.pause=True
        self.assertEqual(self.run_job(lambda _:self.fail('cancelled work'))['result']['reason'],'operator_contact')
        self.assertFalse(self.api.state['enabled'])
    def test_contact_during_work_preserved_in_finish(self):
        def contact(_):
            self.api.state['last_contact_at']=DUE;return dict(passed=True)
        self.run_job(contact)
        self.assertEqual(self.api.state['last_contact_at'],DUE)
        self.assertTrue(self.api.saved[-1]['contact_changed'])
    def test_failed_final_cas_does_not_refund(self):
        def conflict(_): self.api.conflict=True;return dict(passed=True)
        with self.assertRaises(RuntimeError): self.run_job(conflict)
        self.assertEqual(self.api.state['inflight_run_id'],'gh_123_1')
    def test_real_offline_probe_no_model_key(self):
        with patch.dict(os.environ,{'GH_HOST_TOKEN':'DO_NOT_INHERIT','OPENAI_API_KEY':'DO_NOT_INHERIT'}):
            result=host.probe(SOURCE)
        self.assertTrue(result['passed']);self.assertEqual(result['tests'],36)
        self.assertIn('connect',result['network_syscalls_denied'])
    def test_timeout_recorded_without_budget_refund(self):
        def timeout(_): raise subprocess.TimeoutExpired('fixed-probe',60)
        self.assertEqual(self.run_job(timeout)['result']['reason'],'probe_timeout_killed_and_reaped')
        self.assertEqual(self.run_job()['reason'],'daily_budget_used')


if __name__=='__main__': unittest.main()
