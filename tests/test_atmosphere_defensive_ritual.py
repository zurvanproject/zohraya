"""Offline synthetic invariants for the new ATMOSPHERE symbolic defense triad."""
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from atmosphere_defensive_ritual import build,audit,RITUALS,PHASES
from atmosphere_policy import authorize

class DefensiveRitualTests(unittest.TestCase):
    def test_three_rituals_three_passes(self):
        p=build()
        self.assertEqual(p['schema'],'atmosphere-defensive-ritual-triad/1')
        self.assertEqual(p['step_count'],9)
        self.assertEqual(len(p['rituals']),3)
        self.assertTrue(all([x['phase'] for x in r['steps']]==list(PHASES) for r in p['rituals']))

    def test_metadata_is_source_labelled_not_a_quote(self):
        for r in build()['rituals']:
            self.assertTrue(r['book_source']['printed_page']>0)
            self.assertIn('اقتباس',r['basis'])
            self.assertTrue(r['book_source']['motif'])

    def test_no_permissions_or_fake_execution(self):
        p=build()
        self.assertEqual(p['execution'],'NOT_RUN')
        self.assertEqual((p['network'],p['model_calls'],p['server_changes']),(False,0,0))
        self.assertTrue(all(s['execution']=='NOT_RUN' and s['authority']=='none'
            for r in p['rituals'] for s in r['steps']))

    def test_each_ritual_selection(self):
        for ritual in RITUALS:
            p=build(ritual['id'])
            self.assertEqual(len(p['rituals']),1)
            self.assertEqual(p['step_count'],3)
            self.assertEqual(p['rituals'][0]['id'],ritual['id'])
        with self.assertRaises(ValueError):build('sudo')

    def test_json_serializable(self):
        self.assertIn('rituals',json.loads(json.dumps(build(),ensure_ascii=False)))

    def test_policy_audit(self):
        a=audit()
        self.assertTrue(a['passed'])
        self.assertFalse(a['actual_live_host_defense_verified'])
        self.assertTrue(all(a['policy_invariants'].values()))

    def test_ritual_does_not_allow_privileged_bridge_action(self):
        self.assertFalse(authorize('ubuntu_bridge','sync',mode='bounded',source_verified=True).allowed)
        self.assertFalse(authorize('poetic_ritual','shell',mode='bounded',source_verified=True,elevated_approved=True).allowed)

    def test_darkness_is_not_described_as_hostile(self):
        p=build('seven_stars')
        self.assertIn('بدون جنگ با تاریکی',p['rituals'][0]['symbol'])

if __name__=='__main__':unittest.main()
