"""Access-control, confinement and privacy checks using synthetic stores only."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from synthetic_fixture import synthetic_body
from unified_body_v2 import instant
from privacy_boundary import PrivateBodyStore, BoundaryError


class PrivacyChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template=synthetic_body()

    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.parent=Path(temporary.name)
        self.root=self.parent/'private-body'
        self.store,self.token=PrivateBodyStore.create(self.root,deepcopy(self.template),
                                                   sensor_sources=['synthetic-sensor'])
        self.addCleanup(self.store.close)

    def event(self, **overrides):
        return dict(event_id='private-step',
            at_utc=(instant(self.template.owner.wall_utc)+timedelta(seconds=.1)).isoformat(),
            duration_s=.1,external={},requested='observe',expected_revision=0)|overrides

    def state_hash(self):
        return hashlib.sha256((self.root/'state.json').read_bytes()).hexdigest()

    def reject_event(self,event):
        before=self.state_hash()
        with self.assertRaises(BoundaryError):
            self.store.handle(self.token,{'op':'step','event':event})
        self.assertEqual(self.state_hash(),before)

    def test_unauthorized_access_is_denied_and_state_unchanged(self):
        before=self.state_hash()
        with self.assertRaises(PermissionError):
            self.store.handle('private-secret-never-log-this',{'op':'inspect','private_text':'do not log'})
        self.assertEqual(before,self.state_hash())
        audit=(self.root/'audit.json').read_text()
        self.assertNotIn('private-secret',audit)
        self.assertNotIn('do not log',audit)
        self.assertIn('unauthorized',audit)

    def test_authorized_inspect_returns_only_minimal_metadata(self):
        result=self.store.handle(self.token,{'op':'inspect'})
        self.assertEqual(set(result),{'schema','revision','system_count','regional_count'})
        self.assertEqual(result['revision'],0)
        self.assertEqual(result['regional_count'],97)

    def test_authorized_step_commits_and_replay_is_idempotent(self):
        request={'op':'step','event':self.event()}
        result=self.store.handle(self.token,request)
        self.assertEqual(result['revision'],1)
        before=self.state_hash()
        self.assertEqual(self.store.handle(self.token,request),result)
        self.assertEqual(self.state_hash(),before)
        self.assertNotIn(self.token,(self.root/'state.json').read_text())
        self.assertNotIn(self.token,(self.root/'policy.json').read_text())

    def test_unknown_event_keys_and_shell_requests_cannot_change_state(self):
        self.reject_event(self.event(shell='private command'))
        self.reject_event(self.event(path='../outside.json'))

    def test_unregistered_sensor_source_is_denied(self):
        self.reject_event(self.event(external={'sensors':{'touch':dict(value=.2,
            source_id='unregistered',sampled_at_s=self.template.owner.owner.body.state.time_s,
            kind='declared_simulated_input')}}))

    def test_registered_sensor_source_is_accepted(self):
        event=self.event(external={'sensors':{'touch':dict(value=.2,
            source_id='synthetic-sensor',sampled_at_s=self.template.owner.owner.body.state.time_s,
            kind='declared_simulated_input')}})
        self.assertEqual(self.store.handle(self.token,{'op':'step','event':event})['revision'],1)

    def test_external_sample_with_unregistered_source_is_denied(self):
        self.reject_event(self.event(external={'native':{'physical_samples':[dict(
            source_id='unregistered',timestamp_utc=self.template.owner.wall_utc,measurements={'x':1.})]}}))

    def test_expensive_and_oversized_requests_are_denied(self):
        self.reject_event(self.event(duration_s=60.))
        self.reject_event(self.event(external={'native':{'imagery':['private text '*2000]}}))

    def test_arbitrary_file_read_operation_is_denied(self):
        before=self.state_hash()
        with self.assertRaises(BoundaryError):
            self.store.handle(self.token,{'op':'read','path':'../outside'})
        self.assertEqual(self.state_hash(),before)

    def test_symlink_state_cannot_read_or_change_an_outside_target(self):
        outside=self.parent/'outside.json'
        outside.write_bytes((self.root/'state.json').read_bytes())
        outside.chmod(0o600)
        before=outside.read_bytes()
        (self.root/'state.json').unlink()
        (self.root/'state.json').symlink_to(outside)
        with self.assertRaises(BoundaryError):
            self.store.handle(self.token,{'op':'step','event':self.event()})
        self.assertEqual(outside.read_bytes(),before)

    def test_hardlinked_state_is_denied(self):
        os.link(self.root/'state.json',self.parent/'linked-state.json')
        with self.assertRaises(BoundaryError):
            self.store.handle(self.token,{'op':'inspect'})

    def test_permissions_are_private_and_broadening_them_fails_closed(self):
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode),0o700)
        for name in ('state.json','policy.json','audit.json','boundary.lock'):
            self.assertEqual(stat.S_IMODE((self.root/name).stat().st_mode),0o600)
        (self.root/'state.json').chmod(0o644)
        with self.assertRaises(BoundaryError):
            self.store.handle(self.token,{'op':'inspect'})

    def test_symlink_vault_root_is_denied(self):
        alias=self.parent/'vault-link'
        alias.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(OSError):
            PrivateBodyStore(alias)

    def test_existing_directory_is_never_adopted_or_overwritten(self):
        before=self.state_hash()
        with self.assertRaises(FileExistsError):
            PrivateBodyStore.create(self.root,deepcopy(self.template))
        self.assertEqual(self.state_hash(),before)

    def test_stale_revision_is_denied_without_changing_state(self):
        self.store.handle(self.token,{'op':'step','event':self.event()})
        self.reject_event(self.event(event_id='new-with-old-revision'))

    def test_audit_history_is_bounded_and_does_not_keep_request_payloads(self):
        for index in range(140):
            with self.assertRaises(PermissionError):
                self.store.handle('invalid',{'op':'inspect','private':str(index)})
        rows=json.loads((self.root/'audit.json').read_text())
        self.assertEqual(len(rows),128)
        self.assertTrue(all(set(row)=={'at_utc','operation','outcome','reason'} for row in rows))

    def test_corrupted_state_is_denied(self):
        state=json.loads((self.root/'state.json').read_text())
        state['payload']['revision']+=1
        (self.root/'state.json').write_text(json.dumps(state))
        with self.assertRaises(BoundaryError):
            self.store.handle(self.token,{'op':'inspect'})


if __name__=='__main__':
    unittest.main(verbosity=2)
