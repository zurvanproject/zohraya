from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from time_mining import EvidenceReuse,digest,verify


class MiningChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=EvidenceReuse(self.tmp.name)
        self.task=dict(impulse=[2.,0.],friction=.6,seconds=.1,dt=.1)

    def test_cached_result_does_not_compute(self):
        first=self.store.execute(self.task)
        with patch('time_mining.compute',side_effect=AssertionError('cache recomputed')):
            again=self.store.execute(self.task)
        self.assertEqual(first['receipt'],again['receipt']);self.assertEqual(again['actual_ticks'],0)

    def test_reproduce_is_a_new_execution(self):
        self.store.execute(self.task)
        second=self.store.execute(self.task,'reproduce')
        self.assertEqual(second['mode'],'fresh_reproduction');self.assertEqual(second['actual_ticks'],1)

    def test_new_context_does_not_reuse(self):
        self.store.execute(self.task);task=self.task|{'impulse':[-2.,0.]}
        result=self.store.execute(task)
        self.assertEqual(result['mode'],'fresh_compute');self.assertEqual(result['actual_ticks'],1)

    def test_tampered_source_and_wrong_task_reject(self):
        original=self.store.execute(self.task)['receipt']
        bad=deepcopy(original);bad['payload']['sources']={};bad['sha256']=digest(bad['payload'])
        with self.assertRaises(ValueError):verify(bad,self.task)
        with self.assertRaises(ValueError):verify(original,self.task|{'friction':.3})

    def test_corrupt_accounting_not_silently_recomputed(self):
        result=self.store.execute(self.task)['receipt'];result['payload']['result']['fuel_J']-=1
        result['sha256']=digest(result['payload']);self.store.path(self.task).write_text(json.dumps(result))
        with patch('time_mining.compute',side_effect=AssertionError('corrupt evidence silently recomputed')):
            with self.assertRaises(ValueError):self.store.execute(self.task)


if __name__=='__main__':unittest.main()
