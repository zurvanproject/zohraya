import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

FILE = Path(__file__).resolve().parents[1] / 'tools/fullbody_online_stage0.py'
spec = importlib.util.spec_from_file_location('fullbody_online_stage0', FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fixture(path):
    data = {
        'systems': [{'id': str(i)} for i in range(12)],
        'nodes': [{'id': f'n{i}'} for i in range(97)],
        'routes': [{'id': str(i)} for i in range(31)],
        'baseline_contract': {
            'adult_scale': {'ground_to_crown_cm': 250, 'mass_target_kg': 195},
            'phenotype_contract': {'horns': 2, 'toes_per_foot': 3, 'digitigrade': True},
        },
    }
    path.write_text(json.dumps(data), encoding='utf-8')
    return data


class Tests(unittest.TestCase):
    def test_approved_urls(self):
        self.assertTrue(mod.approved_url('https://3d.nih.gov/terms'))
        self.assertFalse(mod.approved_url('http://3d.nih.gov/terms'))
        self.assertFalse(mod.approved_url('https://3d.nih.gov.evil.net/terms'))
        self.assertFalse(mod.approved_url('https://x:pass@3d.nih.gov/terms'))
        self.assertFalse(mod.approved_url('https://3d.nih.gov:444/terms'))

    def test_external_redirect_blocked(self):
        with self.assertRaises(ValueError):
            mod.ApprovedRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example/')

    def test_inventory_counts_and_locks(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'anatomy.json'
            fixture(path)
            baseline, gaps = mod.inventory(path)
            self.assertEqual(baseline['existing_counts'], {'systems': 12, 'nodes': 97, 'routes': 31})
            self.assertEqual(len(gaps['nodes']), 97)
            self.assertTrue(all(len(x['requirements']) == 14 for x in gaps['nodes']))
            self.assertEqual(baseline['canonical_design_target']['tail_centerline_cm'], 85)
            self.assertEqual(baseline['legacy_native_scale_unmodified']['mass_target_kg'], 195)

    def test_bad_morphology_and_counts_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'a.json'
            data = fixture(path)
            data['baseline_contract']['phenotype_contract']['digitigrade'] = False
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'baseline_morphology_conflict'):
                mod.inventory(path)
            data = fixture(path)
            data['nodes'].pop()
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'counts_mismatch'):
                mod.inventory(path)

    def test_offline_receipts_no_mutations(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            anatomy = root/'a.json'
            fixture(anatomy)
            output = root/'run-1'
            result = mod.run(anatomy, output, online=False)
            self.assertFalse(result['model_completed'])
            self.assertTrue(result['approvals_required_before_any_model_change'])
            self.assertEqual(len(list(output.iterdir())), 5)
            self.assertEqual(json.loads((output/'candidate_changes.json').read_text())['candidates'], [])
            self.assertTrue(all(x == 'NOT_CHECKED_OFFLINE' for x in result['network_reachability'].values()))
            with self.assertRaises(FileExistsError):
                mod.run(anatomy, output, online=False)

    def test_online_probe_does_not_claim_measurements(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            anatomy = root/'a.json'
            fixture(anatomy)
            def fake_probe(source):
                return {'id': source[0], 'network_status': 'HTTPS_REACHABLE', 'measured_anatomy': False}
            result = mod.run(anatomy, root/'online', online=True, probe_func=fake_probe)
            self.assertTrue(all(x == 'HTTPS_REACHABLE' for x in result['network_reachability'].values()))
            with self.assertRaisesRegex(ValueError, 'cannot_claim'):
                mod.run(anatomy, root/'bad', online=True,
                        probe_func=lambda s: {'id': s[0], 'network_status': 'OK', 'measured_anatomy': True})
            self.assertFalse((root/'bad').exists())


if __name__ == '__main__':
    unittest.main()
