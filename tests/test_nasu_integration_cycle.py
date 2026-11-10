"""Integration contracts, not a learning benchmark. Derived scenarios are labeled."""
from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.nasu_integration_cycle import (
    ROOT, KEYS, PINS, Evidence, EvidenceLedger, cycle, recall, verify_sources,
)


def inputs():
    ci = json.loads((ROOT / 'docs/evidence/public-ci-witness-v01/frozen-public-github-runs.json').read_text(encoding='utf-8'))
    bridge = json.loads((ROOT / 'docs/evidence/integrated-cycle-v01/bridge-observation.json').read_text(encoding='utf-8'))
    return ci, bridge


def simulated_reply(bridge, result, ident=9900000001):
    output = deepcopy(bridge)
    output['comments'].append({
        'id': ident, 'user': {'login': 'zurvanproject'},
        'body': ('Nasuraya Bridge v2 result; request_id=comment-6771977584; '
                 'command=run nasu_wholebody_phase1\nResult: ' + result),
    })
    return output


SUCCESS = 'OK ATLAS=INVENTORY;NODES=97;SYSTEMS=12;ROUTES=31;EXTRA=35;PHYSICS=UNVERIFIED;REG=abc;GAPS=def'


class IntegratedCycleTests(unittest.TestCase):
    def test_existing_sources_are_unchanged_pinned_modules(self):
        verify_sources()
        self.assertEqual(len(PINS), 5)

    def test_actual_observed_queue_selects_bridge_inspection(self):
        ci, bridge = inputs()
        with tempfile.TemporaryDirectory() as td:
            result = cycle(Path(td) / 'research.sqlite', ci, bridge, 1, 'public_observation')
        self.assertEqual(result['atlas_state'], 'QUEUED_NO_RECEIPT')
        self.assertEqual(result['moltbook_state'], 'QUEUED_NO_RECEIPT')
        self.assertEqual(result['recommendation']['selected_route'], 'inspect_bridge_readonly')
        self.assertFalse(result['recommendation']['execution_performed'])

    def test_same_snapshot_replay_does_not_inflate_memory(self):
        ci, bridge = inputs()
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'research.sqlite'
            cycle(db, ci, bridge, 1, 'public_observation')
            repeated = cycle(db, ci, bridge, 2, 'public_observation')
            self.assertEqual(repeated['ingestion'], 'REPLAY_IGNORED')
            self.assertEqual(repeated['sequence'], 1)
            with EvidenceLedger(db) as ledger:
                self.assertEqual(ledger.conn.execute('SELECT COUNT(*) FROM evidence').fetchone()[0], 4)
                self.assertEqual(ledger.conn.execute('SELECT COUNT(*) FROM integration_batches').fetchone()[0], 1)

    def test_new_python_process_recalls_same_decision(self):
        ci, bridge = inputs()
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'research.sqlite'
            written = cycle(db, ci, bridge, 1, 'public_observation')
            completed = subprocess.run(
                [sys.executable, '-m', 'tools.nasu_integration_cycle', '--db', str(db), '--recall'],
                cwd=str(ROOT), capture_output=True, text=True, check=True, timeout=20,
            )
            restored = json.loads(completed.stdout)
            self.assertEqual(restored['recommendation'], written['recommendation'])
            self.assertEqual(restored['fingerprint'], written['fingerprint'])

    def test_synthetic_success_changes_recalled_next_step(self):
        ci, bridge = inputs()
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'synthetic.sqlite'
            before = cycle(db, ci, bridge, 1, 'synthetic_test')
            after = cycle(db, ci, simulated_reply(bridge, SUCCESS), 2, 'synthetic_test')
            self.assertEqual(before['recommendation']['selected_route'], 'inspect_bridge_readonly')
            self.assertEqual(after['recommendation']['selected_route'], 'review_atlas_inventory_readonly')
            self.assertTrue(after['route_changed'])
            self.assertEqual(after['input_tier'], 'synthetic_test')
            self.assertFalse(after['remote_execution_proven'])

    def test_old_known_snapshot_cannot_reverse_new_decision(self):
        ci, bridge = inputs()
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'synthetic.sqlite'
            cycle(db, ci, bridge, 1, 'synthetic_test')
            cycle(db, ci, simulated_reply(bridge, SUCCESS), 2, 'synthetic_test')
            replay = cycle(db, ci, bridge, 3, 'synthetic_test')
            self.assertEqual(replay['ingestion'], 'REPLAY_IGNORED')
            self.assertEqual(replay['sequence'], 2)
            self.assertEqual(replay['recommendation']['selected_route'], 'review_atlas_inventory_readonly')

    def test_stale_unseen_snapshot_rejected_without_change(self):
        ci, bridge = inputs()
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'synthetic.sqlite'
            cycle(db, ci, simulated_reply(bridge, SUCCESS), 3, 'synthetic_test')
            with self.assertRaisesRegex(ValueError, 'stale_or_conflicting'):
                cycle(db, ci, bridge, 2, 'synthetic_test')
            self.assertEqual(recall(db, 'synthetic_test')['sequence'], 3)

    def test_conflicting_receipts_rotate_to_review_not_repost(self):
        ci, bridge = inputs()
        changed = simulated_reply(bridge, SUCCESS)
        changed = simulated_reply(changed, 'JOB_FAILED', ident=9900000002)
        with tempfile.TemporaryDirectory() as td:
            result = cycle(Path(td) / 's.sqlite', ci, changed, 1, 'synthetic_test')
        self.assertEqual(result['recommendation']['selected_route'], 'resolve_evidence_conflict_readonly')
        self.assertFalse(result['recommendation']['execution_performed'])

    def test_reported_failure_selects_failure_review(self):
        ci, bridge = inputs()
        with tempfile.TemporaryDirectory() as td:
            result = cycle(Path(td) / 's.sqlite', ci, simulated_reply(bridge, 'JOB_TIMEOUT'), 1, 'synthetic_test')
        self.assertEqual(result['recommendation']['selected_route'], 'review_job_failure_readonly')

    def test_external_reposting_and_command_resending_always_blocked(self):
        ci, bridge = inputs()
        states = [bridge, simulated_reply(bridge, SUCCESS), simulated_reply(bridge, 'JOB_FAILED')]
        for state in states:
            with tempfile.TemporaryDirectory() as td:
                result = cycle(Path(td) / 's.sqlite', ci, state, 1, 'synthetic_test')
            denied = result['recommendation']['rejected_routes']
            for action in ('resend_atlas_command', 'publish_moltbook_again'):
                self.assertIn('approval_missing', denied[action])

    def test_edited_report_in_database_stops_instead_of_recall(self):
        ci, bridge = inputs()
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 's.sqlite'
            cycle(db, ci, bridge, 1, 'synthetic_test')
            with EvidenceLedger(db) as ledger:
                ledger.conn.execute("UPDATE integration_batches SET report_json='{}'")
                ledger.conn.commit()
            with self.assertRaisesRegex(ValueError, 'integrity_mismatch'):
                recall(db, 'synthetic_test')

    def test_uncommitted_partial_future_evidence_not_promoted(self):
        ci, bridge = inputs()
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 's.sqlite'
            cycle(db, ci, bridge, 1, 'synthetic_test')
            with EvidenceLedger(db) as ledger:
                ledger.append(Evidence('partial:2', 'synthetic_test', KEYS[0], 'A', 2,
                                       'partial_observer', 'independent_execution', True))
            result = recall(db, 'synthetic_test')
            self.assertEqual(result['sequence'], 1)
            self.assertEqual(result['recommendation']['selected_route'], 'inspect_bridge_readonly')

    def test_synthetic_and_actual_observations_stay_separate(self):
        ci, bridge = inputs()
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 's.sqlite'
            cycle(db, ci, bridge, 1, 'public_observation')
            cycle(db, ci, simulated_reply(bridge, SUCCESS), 1, 'synthetic_test')
            self.assertEqual(recall(db, 'public_observation')['atlas_state'], 'QUEUED_NO_RECEIPT')
            self.assertEqual(recall(db, 'synthetic_test')['atlas_state'], 'REPORTED_INVENTORY')

    def test_integration_never_uses_gate_network_reader(self):
        ci, bridge = inputs()
        with patch('tools.fourway_evidence_gate_v02.fetch_live_issue_comments', side_effect=AssertionError('network')):
            with tempfile.TemporaryDirectory() as td:
                cycle(Path(td) / 's.sqlite', ci, bridge, 1, 'public_observation')


if __name__ == '__main__':
    unittest.main()
