"""Offline contract tests; no VPS, root, downloads, credentials or sockets."""
import importlib.util
import json
from pathlib import Path
from unittest import TestCase, mock
import unittest

ROOT = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

worker = load('nasu_v2_worker', ROOT/'tools/bridge_v2/worker.py')
patcher = load('nasu_v2_patcher', ROOT/'tools/bridge_v2/patch_bridge.py')

BRIDGE_FIXTURE = r'''import re
COMMAND_RE = re.compile(r"(?m)^\s*nasu-linux:\s*(status|repo|awake-status|workload-status|stage0-offline|help)\s*$", re.I)
def dispatch(action):
    if action == "status":
        return "ok"
    if action == "stage0-offline":
        return "ok"
    return "Allowed: status, repo, awake-status, workload-status, stage0-offline, help. No arbitrary shell."
def all_comments():
    return []
'''

class BridgeV2Contracts(TestCase):
    def test_patch_preserves_existing_commands(self):
        out = patcher.patch(BRIDGE_FIXTURE)
        self.assertIn('workload-status', out)
        self.assertIn('stage0-offline', out)
        self.assertIn('v2-audit', out)
        self.assertIn('v2-inventory', out)
        self.assertIn('v2-sources', out)
        self.assertIn('No arbitrary shell.', out)

    def test_patch_refuses_duplicate(self):
        with self.assertRaisesRegex(RuntimeError, 'ALREADY_PATCHED'):
            patcher.patch(patcher.patch(BRIDGE_FIXTURE))

    def test_patch_refuses_older_main_bridge(self):
        with self.assertRaisesRegex(RuntimeError, 'REQUIRES_STAGE0_DEPLOYED'):
            patcher.patch(BRIDGE_FIXTURE.replace('stage0-offline|', '').replace('stage0-offline, ', ''))

    def test_patch_refuses_regex_injection(self):
        with self.assertRaisesRegex(RuntimeError, 'UNEXPECTED_COMMAND_PATTERN'):
            patcher.patch(BRIDGE_FIXTURE.replace('workload-status|', '.*|'))

    def test_no_user_supplied_command(self):
        with self.assertRaisesRegex(RuntimeError, 'UNSUPPORTED_FIXED_ACTION'):
            worker.main(['sources', 'http://127.0.0.1/'])

    def test_private_ip_blocked(self):
        with mock.patch.object(worker.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout='127.0.0.1 STREAM host\n')):
            with self.assertRaisesRegex(RuntimeError, 'NONPUBLIC'):
                worker.resolve_public_ips('example.org')

    def test_public_dns_dedup(self):
        with mock.patch.object(worker.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout='1.1.1.1 STREAM example\n1.1.1.1 DGRAM example\n')):
            self.assertEqual(worker.resolve_public_ips('example.org'), ['1.1.1.1'])

    def test_dns_timeout(self):
        with mock.patch.object(worker, 'resolve_public_ips', side_effect=RuntimeError('DNS_RESOLUTION_FAILED')):
            x=worker.probe_one('test','https://www.nlm.nih.gov/research/visible/visible_human.html')
            self.assertEqual(x['dns'],'FAILED')
            self.assertEqual(x['tls'],'NOT_CHECKED')
            self.assertFalse(x['anatomy_measured'])

    def test_dry_run_syntax_validation_has_no_pycache_side_effect(self):
        installer = (ROOT/'tools/bridge_v2/install.sh').read_text(encoding='utf-8')
        self.assertIn('ast.parse(', installer)
        self.assertNotIn('py_compile', installer)
        self.assertIn("mode=\"${1:---dry-run}\"", installer)

    def test_source_list_is_fixed(self):
        self.assertEqual(len(worker.SOURCES),4)
        self.assertEqual(set(worker.SOURCES), {'nlm_vhp','nih_3d','opensim','mujoco'})
        self.assertTrue(all(u.startswith('https://') for u in worker.SOURCES.values()))

    def test_inventory_never_claims_real_geometry(self):
        import hashlib
        atlas = json.dumps({'systems':[{}]*12,'nodes':[{}]*97,'routes':[{}]*31,
                            'baseline_contract':{'phenotype_contract':{'horns':2,'toes_per_foot':3,'digitigrade':True}}}).encode()
        mission = json.dumps({'morphology_constraints':{'target_mass_kg':78,'ground_to_crown_cm':170,'tail_centerline_cm':85}}).encode()
        with mock.patch.object(worker, 'checked_file', side_effect=[atlas, mission]):
            result=worker.inventory()
        self.assertFalse(result['body_validated'])
        self.assertFalse(result['body_modified'])
        self.assertEqual(result['unverified_requirements'],1358)

    def test_inventory_checksum_mismatch_fails_closed(self):
        with mock.patch.object(worker, 'checked_file', side_effect=RuntimeError('PIN_MISMATCH')):
            with self.assertRaisesRegex(RuntimeError,'PIN_MISMATCH'):
                worker.inventory()

if __name__=='__main__': unittest.main()
