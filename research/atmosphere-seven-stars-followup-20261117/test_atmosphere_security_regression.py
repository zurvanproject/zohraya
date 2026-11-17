"""CI regression: explicit trust policy, independent approvals, and atomic backup publication.

Synthetic keys / SQLite only. Linux SIGKILL fault injection.
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from atmosphere_attestation import (EvidenceOutbox, PinnedRoot, TrustedRoots, sha, MANIFEST_SCHEMA,
                                     envelope_for, commitment, canonical, iso)
from atmosphere_awake_adapter import ControlledAwakeAdapter
from atmosphere_recovery import create_snapshot, restore_to_new_directory, verify_sealed_backup

NOW = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
METRICS = ("sensory_load", "prediction_error", "sensory_occurrence",
           "goal_selected", "dios_sensory_stance", "action_matches")
VALUES = (.4, .6, True, 1, "needs_review", True)
COMMIT = "d86750d8d26d4ea6a3fe595f9e1ee81e95d81fec"


def keypair():
    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return private, PinnedRoot(raw.hex(), hashlib.sha256(raw).hexdigest())


def batch(prefix="synthetic", overrides=None):
    overrides = overrides or {}
    rows = []
    for topic, value in zip(METRICS, VALUES):
        row = {"event_id": f"{prefix}-1-{topic}", "topic": f"shared.demo.{topic}",
               "source_ref": f"https://github.com/zurvanproject/zohraya/commit/{COMMIT}",
               "observed_at": "2026-11-17T09:00:00Z", "sample_time": 1.6,
               "confidence": 0.7, "value": overrides.get(topic, value)}
        rows.append(envelope_for(row, source_id="stage3-pr198", source_revision="a" * 64))
    return rows


def sign(priv, env):
    unsigned = {"schema": MANIFEST_SCHEMA, "issued_at": iso(NOW-timedelta(minutes=1)),
                "expires_at": iso(NOW+timedelta(hours=2)),
                "commitments": [commitment(e) for e in env]}
    return {**unsigned, "signature_ed25519": priv.sign(canonical(unsigned)).hex()}


class FakeCore:
    """Durable idempotent stand-in for pinned Awake core; no model, DIOS, or network."""
    @staticmethod
    def ingest(root, rows, *, now):
        p = Path(root)
        p.mkdir(parents=True, exist_ok=True)
        added, dup = 0, 0
        with sqlite3.connect(p / 'awake.sqlite3') as db:
            db.execute("CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY,payload TEXT NOT NULL)")
            for row in rows:
                payload = {**row, 'sample_time': float(row['sample_time']),
                           'confidence': float(row['confidence'])}
                raw = json.dumps(payload, sort_keys=True)
                old = db.execute('SELECT payload FROM evidence WHERE id=?', (row['event_id'],)).fetchone()
                if old:
                    if json.loads(old[0]) != payload:
                        raise ValueError('conflicting-awake-evidence')
                    dup += 1
                else:
                    db.execute('INSERT INTO evidence VALUES (?,?)', (row['event_id'], raw))
                    added += 1
        return {'status':'ingested', 'added':added, 'duplicate':dup}


class DummyBridge:
    pass


def die_in_child(fn):
    pid = os.fork()
    if pid == 0:
        try:
            fn()
        except BaseException as exc:
            print('CHILD_EXC', repr(exc), flush=True)
            os._exit(31)
        os._exit(32)  # should have been killed by deliberate fault
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)



class HardenedRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.key_a, self.root_a = keypair()
        self.policy_a = TrustedRoots(active=self.root_a)
        self.outbox = EvidenceOutbox(self.base / 'outbox' / 'events.sqlite3')

    def stage(self, env, key, policy):
        manifest = sign(key, env)
        self.outbox.stage(env, manifest=manifest, root=policy, now=NOW)
        return manifest

    def test_valid_signer_alone_cannot_deliver_without_independent_pin(self):
        forged = batch('forged', overrides={'goal_selected':999})
        manifest = self.stage(forged, self.key_a, self.policy_a)
        adapter = ControlledAwakeAdapter(outbox_path=self.outbox.path,
                                         awake_root=self.base / 'awake',
                                         trusted_core_sha256='1'*64,
                                         trusted_bridge_sha256='2'*64)
        with patch.object(ControlledAwakeAdapter,'_modules',return_value=(FakeCore,DummyBridge)):
            with self.assertRaisesRegex(ValueError,'independent-delivery-approval-required'):
                adapter.deliver_pending(root=self.policy_a,now=NOW)
            with self.assertRaisesRegex(ValueError,'unapproved-signed-manifest'):
                adapter.deliver_pending(root=self.policy_a,now=NOW,
                                        approved_manifest_sha256=frozenset({'0'*64}))
            self.assertFalse((self.base / 'awake' / 'awake.sqlite3').exists())
            # Manual authorization is a second, explicit trust input; no claim it proves truth.
            approval = frozenset({sha(canonical(manifest))})
            receipt = adapter.deliver_pending(root=self.policy_a,now=NOW,
                                            approved_manifest_sha256=approval)
        self.assertEqual(receipt['delivered'],6)

    def test_rotation_with_old_and_new_roots_pending(self):
        self.stage(batch('old'), self.key_a, self.policy_a)
        key_b, root_b = keypair()
        policy_b = TrustedRoots(active=root_b, historical=(self.root_a,))
        self.stage(batch('new'), key_b, policy_b)
        groups = self.outbox.pending_bundles(root=policy_b,now=NOW)
        self.assertEqual(len(groups),2)
        self.assertEqual(sorted(len(g) for g in groups),[6,6])
        policy_revoked_a = TrustedRoots(active=root_b, historical=(self.root_a,),
                                        revoked=(self.root_a.fingerprint,))
        with self.assertRaisesRegex(ValueError,'revoked-evidence-root'):
            self.outbox.pending_bundles(root=policy_revoked_a,now=NOW)
        with self.assertRaisesRegex(ValueError,'invalid-signature'):
            self.outbox.stage(batch('old-after'),manifest=sign(self.key_a,batch('old-after')),
                              root=policy_revoked_a,now=NOW)
        self.assertEqual(self.outbox.stats(),{'pending':12,'delivered':0})

    def make_backup(self):
        awake_db = self.base / 'live-awake' / 'awake.sqlite3'
        awake_db.parent.mkdir()
        with sqlite3.connect(awake_db) as db:
            for name in ('control','evidence','questions','ticks','ledger'):
                db.execute(f'CREATE TABLE {name}(id TEXT PRIMARY KEY)')
        archive = self.base / 'archive' / 'snap'
        return awake_db,archive

    def test_kill_before_publish_leaves_no_partial_target(self):
        awake,archive = self.make_backup()
        def child():
            import atmosphere_recovery as r
            with patch.object(r,'_publish_directory_noreplace',side_effect=lambda *_:os._exit(77)):
                create_snapshot(awake_db=awake,outbox_db=self.outbox.path,
                                archive_dir=archive,now=NOW)
        self.assertEqual(die_in_child(child),77)
        self.assertFalse(archive.exists())
        receipt = create_snapshot(awake_db=awake,outbox_db=self.outbox.path,
                                  archive_dir=archive,now=NOW)
        self.assertEqual({p.name for p in archive.iterdir()},
                         {'awake.sqlite3','evidence_outbox.sqlite3','UNSIGNED_RECEIPT.json'})

    def test_kill_after_publish_leaves_complete_target(self):
        awake,archive = self.make_backup()
        def child():
            import atmosphere_recovery as r
            old = r._publish_directory_noreplace
            def killed(src,dst):
                old(src,dst)
                os._exit(78)
            with patch.object(r,'_publish_directory_noreplace',side_effect=killed):
                create_snapshot(awake_db=awake,outbox_db=self.outbox.path,
                                archive_dir=archive,now=NOW)
        self.assertEqual(die_in_child(child),78)
        self.assertEqual({p.name for p in archive.iterdir()},
                         {'awake.sqlite3','evidence_outbox.sqlite3','UNSIGNED_RECEIPT.json'})
        with self.assertRaises(FileExistsError):
            create_snapshot(awake_db=awake,outbox_db=self.outbox.path,
                            archive_dir=archive,now=NOW)

    def test_restore_kill_and_retry_stays_non_destructive(self):
        awake,archive = self.make_backup()
        receipt = create_snapshot(awake_db=awake,outbox_db=self.outbox.path,
                                  archive_dir=archive,now=NOW)
        sealed = {**receipt,'signature_ed25519':self.key_a.sign(canonical(receipt)).hex()}
        pin = sha(canonical(sealed))
        target = self.base / 'restore' / 'new'
        def child():
            import atmosphere_recovery as r
            with patch.object(r,'_publish_directory_noreplace',side_effect=lambda *_:os._exit(79)):
                restore_to_new_directory(archive,target,sealed,
                                         root=self.root_a,expected_receipt_sha256=pin)
        self.assertEqual(die_in_child(child),79)
        self.assertFalse(target.exists())
        ret = restore_to_new_directory(archive,target,sealed,
                                       root=self.root_a,expected_receipt_sha256=pin)
        self.assertFalse(ret['live_activated'])
        self.assertTrue(awake.exists())
        self.assertEqual({p.name for p in target.iterdir()},
                         {'awake.sqlite3','evidence_outbox.sqlite3'})

if __name__=='__main__':unittest.main()
