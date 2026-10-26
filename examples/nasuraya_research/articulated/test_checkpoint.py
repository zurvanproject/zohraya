"""Snapshot contract tests against a retained, synthetic mechanical fixture."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from .checkpoint import restore_checkpoint, integration_state, digest
from .evaluate import load
from .resize import SMALL
from .build import ROOT


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.cp=json.loads((ROOT/'evidence/articulated-continuity-v02/first-checkpoint.json').read_text())
        self.model,self.data=load(SMALL)
        self.parameters=self.cp['value']['parameters']

    def test_exact_integration_and_controller_restore(self):
        c,feet,com,height,next_step,ticks=restore_checkpoint(self.cp,self.model,self.data,self.parameters)
        p=self.cp['value']
        np.testing.assert_array_equal(integration_state(self.model,self.data),p['integration'])
        np.testing.assert_array_equal(self.data.qpos,p['qpos'])
        np.testing.assert_array_equal(self.data.qvel,p['qvel'])
        np.testing.assert_array_equal(c.prev,p['controller']['prev'])
        np.testing.assert_array_equal(c.previous_solution,p['controller']['previous_solution'])
        np.testing.assert_array_equal(feet,p['feet'])
        self.assertEqual(next_step,1)
        self.assertEqual(float(self.data.time),p['time'])

    def test_tampered_payload_rejected_before_body_mutation(self):
        before=self.data.qpos.copy()
        self.cp['value']['qpos'][0]+=1
        with self.assertRaises(ValueError):restore_checkpoint(self.cp,self.model,self.data,self.parameters)
        np.testing.assert_array_equal(self.data.qpos,before)

    def test_parameter_or_source_drift_rejected(self):
        with self.assertRaises(ValueError):
            restore_checkpoint(self.cp,self.model,self.data,dict(self.parameters,friction=.1))
        with patch('examples.nasuraya_research.articulated.checkpoint.source_contract',return_value={}):
            with self.assertRaises(ValueError):restore_checkpoint(self.cp,self.model,self.data,self.parameters)

    def test_nonfinite_or_wrong_shape_rejected(self):
        for value in ([float('nan')], []):
            cp=deepcopy(self.cp);cp['value']['integration']=value
            if value: # Nonfinite values cannot even receive a valid canonical hash.
                with self.assertRaises(ValueError):restore_checkpoint(cp,self.model,self.data,self.parameters)
            else:
                cp['sha256']=digest(cp['value'])
                with self.assertRaises(ValueError):restore_checkpoint(cp,self.model,self.data,self.parameters)

    def test_disagreement_between_metadata_and_physics_rejected(self):
        self.cp['value']['time']+=1
        self.cp['sha256']=digest(self.cp['value'])
        with self.assertRaises(ValueError):restore_checkpoint(self.cp,self.model,self.data,self.parameters)


if __name__=='__main__':unittest.main()
