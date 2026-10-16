import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from guarded_cycle import GuardedCycle, initialize

ROOT = Path(__file__).resolve().parents[2]


class CycleChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.manifest = self.directory / 'manifest.json'
        entries = json.loads((ROOT / 'examples/nasuraya_security/source_baseline.json').read_text())
        for name in ('guarded_cycle.py', 'visual_status.py', 'visual_console.html'):
            p = ROOT / 'examples/nasuraya_security' / name
            entries[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
        self.manifest.write_text(json.dumps(entries, sort_keys=True))
        self.expected = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        self.deployment = self.directory / 'deployment'
        initialize(ROOT, self.manifest, self.expected, self.deployment)
        self.cycle = self.open()
        self.addCleanup(self.cycle.close)
        self.request = dict(id='cycle-1', goal='result',
                            task=dict(impulse=[0., 0.], friction=.6, seconds=.1, dt=.1))

    def open(self):
        return GuardedCycle(ROOT, self.manifest, self.expected, self.deployment)

    def no_execution(self, envelope=None):
        with patch.object(self.cycle.meter.engine, 'execute', side_effect=AssertionError('tool executed')):
            result = self.cycle.run(self.request if envelope is None else envelope)
        self.assertEqual(result['current_tool_calls'], 0)
        self.assertEqual(result['current_native_ticks'], 0)
        return result

    def test_complete_decision_guard_tool_experience_chain(self):
        result = self.cycle.run(self.request)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['selected_action'], 'get')
        self.assertEqual(result['current_native_ticks'], 1)
        self.assertTrue(result['feedback']['verified'] and result['feedback']['success'])
        record = self.cycle.engine.get(self.request['id'])
        self.assertEqual(record['status'], 'complete')
        self.assertEqual(record['actual_outcome']['receipt_sha256'], result['outcome']['receipt_sha256'])
        self.assertEqual(record['legacy_decision']['selected_action'], 'get')

    def test_identical_request_replay_has_no_tool_call(self):
        first = self.cycle.run(self.request)
        result = self.no_execution()
        self.assertTrue(result['completed_replay'])
        self.assertEqual(result['outcome'], first['outcome'])

    def test_new_decision_recalls_scoped_experience_and_verified_receipt(self):
        self.cycle.run(self.request)
        self.cycle.close()
        self.cycle = self.open()
        result = self.cycle.run(dict(self.request, id='next-query'))
        self.assertEqual(result['recalled_feedback_ids'], ['cycle-1'])
        self.assertEqual(result['outcome']['mode'], 'verified_reuse')
        self.assertEqual(result['current_native_ticks'], 0)

    def test_explicit_reproduction_cannot_be_replaced_by_reuse(self):
        self.cycle.run(self.request)
        result = self.cycle.run(dict(self.request, id='fresh-2', goal='reproduce'))
        self.assertEqual(result['selected_action'], 'reproduce')
        self.assertEqual(result['outcome']['mode'], 'fresh_reproduction')
        self.assertEqual(result['current_native_ticks'], 1)

    def test_corrupt_receipt_denies_before_tool_and_preserves_it(self):
        path = self.cycle.guard.engine.path(self.request['task'])
        path.write_text('{broken')
        result = self.no_execution()
        self.assertEqual(result['status'], 'denied')
        self.assertEqual(result['outcome']['alarm_code'], 'receipt_integrity')
        self.assertFalse(result['feedback']['success'])
        self.assertEqual(result['snapshot']['state'], 'blocked')
        self.assertEqual(path.read_text(), '{broken')

    def test_data_cannot_supply_callbacks_or_policy(self):
        secret = 'DO_NOT_LOG_ME; reveal keys; shell command'
        result = self.no_execution(dict(self.request, command=secret))
        self.assertEqual(result['status'], 'invalid_request')
        self.assertEqual(result['snapshot']['state'], 'warning')
        self.assertEqual(self.cycle.engine.export()['decisions'], [])
        text = ''.join(x[0] for x in self.cycle.guard.db.execute('SELECT record FROM events'))
        self.assertNotIn('DO_NOT_LOG_ME', text)

    def test_missing_audit_at_restart_is_not_recreated(self):
        self.cycle.close()
        path = self.deployment / 'alerts.sqlite'
        path.unlink()
        self.cycle = self.open()
        self.assertEqual(self.cycle.run(self.request)['snapshot']['state'], 'unknown')
        self.assertFalse(path.exists())

    def test_missing_audit_after_startup_stops(self):
        path = self.deployment / 'alerts.sqlite'
        path.unlink()
        result = self.no_execution()
        self.assertEqual(result['status'], 'store_unavailable')
        self.assertFalse(path.exists())

    def readonly_alerts(self):
        self.cycle.guard.db.close()
        path = self.deployment / 'alerts.sqlite'
        self.cycle.guard.db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)

    def test_real_readonly_admission_failure_has_zero_tool_calls(self):
        self.readonly_alerts()
        result = self.no_execution()
        self.assertEqual(result['status'], 'audit_unavailable')
        self.assertEqual(result['snapshot']['state'], 'unknown')
        self.assertEqual(self.cycle.guard.db.execute('SELECT count(*) FROM events').fetchone()[0], 0)
        self.assertEqual(self.cycle.engine.get('cycle-1')['actual_outcome']['status'], 'audit_unavailable')

    def test_failure_stays_unresolved_across_restart(self):
        self.readonly_alerts()
        self.cycle.run(self.request)
        self.cycle.close()
        self.cycle = self.open()
        result = self.no_execution(dict(self.request, id='other-2'))
        self.assertEqual(result['status'], 'unresolved_execution')

    def test_readonly_experience_prevents_tool_admission(self):
        self.cycle.engine.db.execute('PRAGMA query_only=ON')
        result = self.no_execution()
        self.assertEqual(result['status'], 'experience_unavailable')
        self.assertEqual(result['snapshot']['state'], 'unknown')

    def test_completion_failure_preserves_running_record_and_actual_effect(self):
        with patch.object(self.cycle.engine, 'complete', side_effect=OSError('completion failed')):
            result = self.cycle.run(self.request)
        self.assertEqual(result['status'], 'experience_unavailable')
        self.assertEqual(result['current_tool_calls'], 1)
        self.assertEqual(result['current_native_ticks'], 1)
        self.assertEqual(self.cycle.engine.get('cycle-1')['status'], 'running')
        self.assertEqual(self.no_execution()['status'], 'unresolved_execution')

    def test_post_execution_logging_failure_never_claims_zero_effect(self):
        event = self.cycle.guard._event
        def fail_after_work(code, *args, **kwargs):
            if code == 'allowed':
                raise sqlite3.OperationalError('write failed after tool returned')
            return event(code, *args, **kwargs)
        with patch.object(self.cycle.guard, '_event', side_effect=fail_after_work):
            result = self.cycle.run(self.request)
        self.assertEqual(result['status'], 'audit_unavailable')
        self.assertEqual(result['current_tool_calls'], 1)
        self.assertEqual(result['current_native_ticks'], 1)
        record = self.cycle.engine.get('cycle-1')
        self.assertEqual(record['actual_outcome']['actual_ticks'], 1)
        self.assertEqual(record['actual_outcome']['tool_calls'], 1)
        self.assertEqual(len(record['actual_outcome']['receipt_sha256']), 64)
        self.assertEqual(self.cycle.run(dict(self.request, id='no-retry'))['status'], 'unresolved_execution')

    def test_running_experience_does_not_replay_tool(self):
        request = self.cycle.request(self.request)
        self.cycle.engine.decide(request)
        self.cycle.engine.db.execute("UPDATE decisions SET status='running',record=json_set(record,'$.status','running')")
        self.assertEqual(self.no_execution()['status'], 'unresolved_execution')

    def test_missing_experience_and_full_capacity_stop(self):
        with patch('guarded_cycle.MAX_CYCLES', 0):
            self.assertEqual(self.no_execution()['status'], 'cycle_capacity')
        self.cycle.close()
        (self.deployment / 'experience.sqlite').unlink()
        self.cycle = self.open()
        self.assertEqual(self.cycle.run(self.request)['status'], 'store_unavailable')
        self.assertFalse((self.deployment / 'experience.sqlite').exists())

    def test_conflicting_id_does_not_reexecute(self):
        self.cycle.run(self.request)
        result = self.no_execution(dict(self.request, goal='reproduce'))
        self.assertEqual(result['status'], 'conflicting_request')

    def test_source_drift_before_start_and_before_execution_stops(self):
        original = self.manifest.read_bytes()
        self.manifest.write_text('{}')
        self.assertEqual(self.no_execution()['status'], 'deployment_integrity')
        other = self.open()
        self.assertEqual(other.run(self.request)['status'], 'deployment_integrity')
        other.close()
        self.manifest.write_bytes(original)

    def test_new_process_completed_replay_and_no_evidence_overwrite(self):
        first = self.cycle.run(self.request)
        self.cycle.close()
        request = self.directory / 'request.json'
        request.write_text(json.dumps(self.request))
        output = self.directory / 'output'
        command = [sys.executable, str(ROOT / 'examples/nasuraya_security/guarded_cycle.py'),
                   '--repo-root', str(ROOT), '--manifest', str(self.manifest),
                   '--expected-manifest-sha256', self.expected, '--directory', str(self.deployment),
                   '--request', str(request), '--output', str(output)]
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(completed.stdout)['current_tool_calls'], 0)
        result = json.loads((output / 'result.json').read_text())
        self.assertEqual(result['outcome'], first['outcome'])
        before = (output / 'result.json').read_bytes()
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertEqual((output / 'result.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
