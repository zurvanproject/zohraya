from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .study import (protocol,image,sensor,workspace_trial,circuit_trial,change_edge,
                    Circuit,toy_circuit,BrainBodyLoop,digest,record_start,record_finish)

class ProbeTests(unittest.TestCase):
    def test_frozen_protocol_digest_and_fixed_bounds(self):
        p=protocol();self.assertEqual(p['workspace']['body_ticks_per_arm'],4)
        self.assertEqual(p['circuit']['duration_ms'],320)
        self.assertFalse(p['workspace']['training']);self.assertFalse(p['circuit']['learning'])

    def test_sensor_uses_pixels_without_ground_truth_or_arm(self):
        vertical=[[int(c in (4,5)) for c in range(10)] for r in range(10)]
        horizontal=list(map(list,zip(*vertical)))
        self.assertEqual(sensor(vertical)['value'],0)
        self.assertEqual(sensor(horizontal)['value'],1)
        self.assertTrue(sensor([[0]*10 for _ in range(10)])['tie'])
        with self.assertRaises(ValueError):sensor([[0,2],[0,1]])

    def test_private_edge_intervention_preserves_state_and_rejects_bad_edge(self):
        c=toy_circuit(plastic=False,learned_weight_ns=12.)
        for _ in range(23):c.step({'seat_input':421.})
        before=deepcopy(c.payload());change_edge(c,'association_to_attention',0.)
        after=c.payload()
        for key in ('tick','neurons','pending'):self.assertEqual(before[key],after[key])
        self.assertEqual(after['connections']['association_to_attention']['weight_ns'],0.)
        self.assertEqual(Circuit.restore(after).payload(),after)
        with self.assertRaises(ValueError):change_edge(c,'imaginary_edge',0.)

    def test_original_fixture_and_native_source_not_mutated(self):
        c=toy_circuit(plastic=False);initial=c.payload();other=Circuit.restore(initial)
        change_edge(other,'arm_to_attention',11.)
        self.assertEqual(c.payload(),initial)

    def test_workspace_real_owner_steps_are_bounded_and_cold_restore_exact(self):
        p=protocol()['workspace'];pixels=[[0]*10 for _ in range(10)]
        r=workspace_trial(pixels,'contract','intact',p)
        restored=BrainBodyLoop.restore(r['final'])
        self.assertEqual(restored.body_steps,4)
        self.assertEqual(restored.checkpoint(),r['final'])
        self.assertEqual(len(r['rows']),4)
        self.assertTrue(all(x['receipt']['body_valid'] for x in r['rows']))

    def test_broadcast_intervention_really_changes_native_packet_and_restores(self):
        r=workspace_trial([[0]*10 for _ in range(10)],'cut-contract','broadcast_cut',protocol()['workspace'])
        self.assertEqual(r['rows'][0]['cognition']['packet'],[])
        self.assertEqual(r['rows'][1]['cognition']['plan']['kind'],'no_shared_access')
        self.assertTrue(r['rows'][2]['cognition']['packet'])
        self.assertTrue(r['final']['payload']['brain']['payload']['config']['broadcast'])

    def test_work_quotas_and_safety_gates_remain_native(self):
        from cognitive_workspace_v07 import EnvironmentBrain,Goal,CognitiveEvent
        brain=EnvironmentBrain(broadcast=False)
        body=dict(sampled_at_s=0.,critical=True,optional_pause=False,valid=True,
                  protective=False,source='V06_physical_owner',phase='double_support',body_tick=0)
        result=brain.step(CognitiveEvent('guard',0.,Goal()),body)
        self.assertEqual(result['plan']['kind'],'hold_for_body')
        self.assertEqual(result['plan']['command'],'stand')
        self.assertLessEqual(result['work_units'],result['work_quota'])

    def test_unknown_arms_cannot_execute(self):
        p=protocol()
        with patch.object(BrainBodyLoop,'step',side_effect=AssertionError('must reject first')):
            with self.assertRaises(ValueError):workspace_trial([[0]*10 for _ in range(10)],'invalid','x',p['workspace'])
        with patch.object(Circuit,'step',side_effect=AssertionError('must reject first')):
            with self.assertRaises(ValueError):circuit_trial({},'x',p['circuit'])

if __name__=='__main__':unittest.main()
