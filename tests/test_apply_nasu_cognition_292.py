"""Real temporary files and snapshot restore; systemd is simulated."""
import contextlib
from functools import partial
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest import mock

from tools import apply_nasu_cognition_292 as update
from tools import install_nasu_server_agent as support

ROOT = Path(__file__).resolve().parents[1]
OLD = subprocess.check_output(['git', '-C', str(ROOT), 'show',
                              'a0e87a07e357ee10698949aa99a7fa1bcb7a6fde:tools/nasu_autonomous_cognition.py'])
# This historical updater installs its immutable release, not the current HEAD.
NEW = subprocess.check_output(['git', '-C', str(ROOT), 'show',
                              update.REVISION + ':tools/nasu_autonomous_cognition.py'])


class UpdateTests(unittest.TestCase):
    def fixture(self, *, active=True, enabled=True):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        target = root / 'nasu_autonomous_cognition.py'
        target.write_bytes(OLD)
        os.chmod(target, 0o644)
        timer = {'active': active, 'enabled': enabled}
        self.timer = timer
        self.busy = False
        self.transitions = []
        dep = types.SimpleNamespace(
            COGNITION=target, BACKUPS=root/'backups', SYSTEM=root/'system',
            COGNITIVE_SERVICE=support.COGNITIVE_SERVICE,
            COGNITIVE_TIMER=support.COGNITIVE_TIMER,
            BRIDGE_SERVICE=support.BRIDGE_SERVICE,
            digest=support.digest, require=support.require,
            DeployError=support.DeployError,
            guarded=lambda p, **kw: support.guarded(p, owner=os.geteuid(), **kw),
            read_file=lambda p: support.read_file(p, owner=os.geteuid()),
            Snapshot=partial(support.Snapshot, owner=os.geteuid(), group=os.getegid()))
        def units(name):
            if name == dep.BRIDGE_SERVICE:
                return {'ActiveState': 'active'}
            return {'LoadState': 'loaded', 'User': 'nasuraya',
                    'FragmentPath': str(dep.SYSTEM/name),
                    'ExecStart': '{ argv[]=/usr/bin/python3 ' + str(target) + ' run; }'}
        def restore(name, state):
            self.transitions.append(('restore', dict(state)))
            timer.update(state)
        def quiesce(state, reason):
            self.transitions.append(('stop_timer', None))
            timer['active'] = False
            if self.busy:
                restore(dep.COGNITIVE_TIMER, state)
                raise support.DeployError(reason)
        dep.unit_state=units
        dep.timer_state=lambda name: dict(timer)
        dep.restore_timer=restore
        dep.quiesce_cognition=quiesce
        return dep

    def test_success_backups_exact_old_bytes_and_preserves_timer(self):
        for active, enabled in ((True, True), (False, False), (False, True)):
            with self.subTest(active=active, enabled=enabled):
                dep=self.fixture(active=active, enabled=enabled)
                result=update.apply_runtime(dep, NEW)
                self.assertEqual(result['UPDATE'], 'APPLIED_RUNTIME_ONLY')
                self.assertEqual(dep.COGNITION.read_bytes(), NEW)
                self.assertEqual(self.timer, {'active':active,'enabled':enabled})
                backup=dep.BACKUPS/('cognition-pr292-'+update.REVISION)
                self.assertEqual((backup/'0.bin').read_bytes(), OLD)
                self.assertEqual(set(json.loads((backup/'manifest.json').read_text())['files']), {str(dep.COGNITION)})
                self.assertFalse(result['model_inference_tested'])

    def test_unknown_installed_version_is_untouched(self):
        dep=self.fixture()
        dep.COGNITION.write_text('unreviewed = True\n')
        with self.assertRaisesRegex(support.DeployError, 'UNKNOWN_INSTALLED'):
            update.apply_runtime(dep, NEW)
        self.assertEqual(self.transitions, [])
        self.assertFalse(dep.BACKUPS.exists())

    def test_busy_service_leaves_no_backup_or_paused_timer(self):
        dep=self.fixture()
        self.busy=True
        with self.assertRaisesRegex(support.DeployError, 'COGNITION_RUNNING'):
            update.apply_runtime(dep, NEW)
        self.assertEqual(dep.COGNITION.read_bytes(), OLD)
        self.assertEqual(self.timer, {'active':True,'enabled':True})
        self.assertFalse(dep.BACKUPS.exists())

    def test_post_write_failure_restores_file_and_timer(self):
        dep=self.fixture()
        original=dep.read_file
        calls=[]
        def reader(path):
            calls.append(path)
            if len(calls)==2:
                raise support.DeployError('SIMULATED_POST_WRITE_FAILURE')
            return original(path)
        dep.read_file=reader
        with self.assertRaisesRegex(support.DeployError, 'UPDATE_FAILED_ROLLED_BACK'):
            update.apply_runtime(dep, NEW)
        self.assertEqual(dep.COGNITION.read_bytes(), OLD)
        self.assertEqual(self.timer, {'active':True,'enabled':True})

    def test_unknown_concurrent_change_is_not_overwritten_on_rollback(self):
        dep=self.fixture()
        original=dep.read_file
        calls=[]
        def reader(path):
            calls.append(path)
            if len(calls)==2:
                path.write_bytes(b'unknown_concurrent_change = True\n')
            return original(path)
        dep.read_file=reader
        with self.assertRaisesRegex(support.DeployError, 'ROLLBACK_INCOMPLETE'):
            update.apply_runtime(dep, NEW)
        self.assertEqual(dep.COGNITION.read_bytes(), b'unknown_concurrent_change = True\n')
        self.assertEqual(self.timer, {'active':True,'enabled':True})

    def test_retry_is_idempotent_only_with_intact_receipt_and_timer(self):
        dep=self.fixture()
        update.apply_runtime(dep, NEW)
        self.transitions.clear()
        self.assertEqual(update.apply_runtime(dep, NEW)['UPDATE'], 'ALREADY_APPLIED')
        self.assertEqual(self.transitions, [])
        self.timer['active']=False
        with self.assertRaisesRegex(support.DeployError, 'TIMER_STATE_DIFFERS'):
            update.apply_runtime(dep, NEW)

    def test_corrected_file_without_receipt_is_not_reported_as_our_install(self):
        dep=self.fixture()
        dep.COGNITION.write_bytes(NEW)
        with self.assertRaisesRegex(support.DeployError, 'WITHOUT_INSTALL_RECEIPT'):
            update.apply_runtime(dep, NEW)

    def test_failed_prior_attempt_requires_review(self):
        dep=self.fixture()
        with mock.patch.object(support.Snapshot, 'apply', side_effect=support.DeployError('SIMULATED_FAILURE')):
            with self.assertRaises(support.DeployError):
                update.apply_runtime(dep, NEW)
        with self.assertRaisesRegex(support.DeployError, 'PRIOR_ATTEMPT'):
            update.apply_runtime(dep, NEW)

    def test_replacement_and_support_are_exact_pinned_sources(self):
        self.assertEqual(support.digest(OLD), update.BEFORE)
        self.assertEqual(support.digest(NEW), update.AFTER)
        self.assertEqual(update.pinned_blob('tools/nasu_autonomous_cognition.py', update.AFTER, project=str(ROOT)), NEW)
        raw=update.pinned_blob('tools/install_nasu_server_agent.py', update.SUPPORT_SHA, project=str(ROOT))
        self.assertEqual(support.digest(raw), update.SUPPORT_SHA)
        with self.assertRaises(ValueError):
            update.pinned_blob('tools/nasu_autonomous_cognition.py', '0'*64, project=str(ROOT))

    def test_unreviewed_replacement_and_symlink_are_rejected(self):
        dep=self.fixture()
        with self.assertRaises(support.DeployError):
            update.apply_runtime(dep, NEW+b'\n')
        actual=dep.COGNITION.with_name('actual.py')
        dep.COGNITION.rename(actual)
        dep.COGNITION.symlink_to(actual)
        with self.assertRaises(support.DeployError):
            update.apply_runtime(dep, NEW)
        self.assertEqual(actual.read_bytes(), OLD)

    def test_new_worktree_runtime_is_rejected_without_side_effects(self):
        candidate = (ROOT / 'tools/nasu_autonomous_cognition.py').read_bytes()
        self.assertNotEqual(support.digest(candidate), update.AFTER)
        dep = self.fixture()
        with self.assertRaisesRegex(support.DeployError, 'UNREVIEWED_REPLACEMENT'):
            update.apply_runtime(dep, candidate)
        self.assertEqual(dep.COGNITION.read_bytes(), OLD)
        self.assertEqual(self.transitions, [])
        self.assertFalse(dep.BACKUPS.exists())

    def test_cli_requires_admin_and_explicit_apply_without_loading_code(self):
        for uid,args in ((1000,['--apply']), (0,[]), (0,['--anything'])):
            with mock.patch.object(os,'geteuid',return_value=uid), contextlib.redirect_stdout(io.StringIO()):
                with mock.patch.object(update,'support',side_effect=AssertionError('must not load')):
                    self.assertEqual(update.main(args),1)


if __name__=='__main__':
    unittest.main()
