"""Independent, synthetic, offline probes against byte-identical PR #257 head modules.

Run: PYTHONPATH=tools python -m unittest discover -s tests -p 'test_additional_threats.py' -v
No real VPS, secrets, workflow, or GitHub writes.
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

from atmosphere_attestation import (EvidenceOutbox, PinnedRoot, MANIFEST_SCHEMA,
                                     envelope_for, commitment, canonical, iso)
from atmosphere_awake_adapter import ControlledAwakeAdapter
from atmosphere_recovery import create_snapshot

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


class ExtraThreatProbes(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.base = Path(self.t.name)
        self.path = self.base / 'outbox' / 'outbox.sqlite3'
        self.box = EvidenceOutbox(self.path)
        self.key_a, self.root_a = keypair()
        self.env_a = batch('legitimate')

    def stage(self, env=None, key=None, root=None):
        env = env or self.env_a
        return self.box.stage(env, manifest=sign(key or self.key_a, env),
                              root=root or self.root_a, now=NOW)

    def adapter(self):
        return ControlledAwakeAdapter(outbox_path=self.path, awake_root=self.base / 'awake',
                                      trusted_core_sha256='1'*64, trusted_bridge_sha256='2'*64)

    def deliver_with(self, adapter, core):
        with patch.object(ControlledAwakeAdapter, '_modules', return_value=(core, DummyBridge)):
            return adapter.deliver_pending(root=self.root_a, now=NOW)

    def test_1_compromised_valid_key_can_inject_six_synthetic_claims(self):
        """Observed risk: crypto/authenticated shape cannot distinguish a malicious valid signer."""
        evil = batch('fabricated', overrides={'sensory_load':0.99, 'goal_selected':999})
        result = self.stage(evil)
        self.assertEqual(result['added'], 6)
        delivered = self.deliver_with(self.adapter(), FakeCore)
        self.assertEqual((delivered['added'], delivered['delivered']), (6,6))
        with sqlite3.connect(self.base / 'awake' / 'awake.sqlite3') as db:
            stored = db.execute('SELECT payload FROM evidence WHERE id=?',
                        ('fabricated-1-goal_selected',)).fetchone()[0]
        self.assertEqual(json.loads(stored)['value'], 999)
        print('OBSERVED valid-key: fabricated metric reached Awake evidence store; authority stays none')

    def test_2_rotated_key_blocks_mixed_pending_queue(self):
        key_b, root_b = keypair()
        self.stage()
        env_b = batch('second')
        self.stage(env_b, key_b, root_b)
        with self.assertRaisesRegex(ValueError, 'outbox-local-integrity-failure'):
            self.box.pending_bundles(root=root_b, now=NOW)
        with self.assertRaisesRegex(ValueError, 'outbox-local-integrity-failure'):
            self.box.pending_bundles(root=self.root_a, now=NOW)
        self.assertEqual(self.box.stats(), {'pending':12,'delivered':0})
        print('OBSERVED rotation: 12 pending, neither single root can enumerate mixed-root queue')

    def test_3_revoked_key_has_no_internal_revocation_state(self):
        self.stage(batch('late'), self.key_a, self.root_a)
        # External operator declares key A revoked, but API accepts a supplied PinnedRoot A.
        # No revocation registry or epoch argument is present in this module.
        self.assertEqual(self.box.stats()['pending'], 6)
        print('OBSERVED revocation: supplying old pinned root still accepts signature; policy external')

    def test_4_sigkill_mid_stage_rolls_back_six_scalar_bundle(self):
        env = batch('crash-stage')
        manifest = sign(self.key_a, env)
        def child():
            import atmosphere_attestation as module
            original_connect = module.sqlite3.connect
            class KillDuringInsert(sqlite3.Connection):
                seen = 0
                def execute(self, sql, *args, **kwargs):
                    value = super().execute(sql, *args, **kwargs)
                    if sql.startswith('INSERT INTO events'):
                        KillDuringInsert.seen += 1
                        if KillDuringInsert.seen == 3:
                            os._exit(73)
                    return value
            def crash_connect(*args,**kwargs):
                return original_connect(*args, factory=KillDuringInsert, **kwargs)
            with patch.object(module.sqlite3,'connect',crash_connect):
                EvidenceOutbox(self.path).stage(env, manifest=manifest, root=self.root_a, now=NOW)
        self.assertEqual(die_in_child(child), 73)
        self.assertEqual(EvidenceOutbox(self.path).stats(), {'pending':0,'delivered':0})
        # New independent process reconstructs connection and stages once.
        again = EvidenceOutbox(self.path)
        receipt = again.stage(env, manifest=manifest, root=self.root_a, now=NOW)
        self.assertEqual(receipt['added'], 6)
        self.assertEqual(again.stats(), {'pending':6,'delivered':0})
        print('OBSERVED stage crash: 0 partially committed; restart stage -> complete 6')

    def test_5_sigkill_after_awake_commit_before_outbox_mark_idempotent(self):
        self.stage()
        def child():
            class CrashAfterCoreCommit:
                @staticmethod
                def ingest(root, rows, *, now):
                    FakeCore.ingest(root, rows, now=now)
                    os._exit(74)
            self.deliver_with(self.adapter(), CrashAfterCoreCommit)
        self.assertEqual(die_in_child(child), 74)
        self.assertEqual(EvidenceOutbox(self.path).stats(), {'pending':6,'delivered':0})
        receipt = self.deliver_with(self.adapter(), FakeCore)
        self.assertEqual((receipt['added'], receipt['duplicate']), (0,6))
        self.assertEqual(EvidenceOutbox(self.path).stats(), {'pending':0,'delivered':6})
        print('OBSERVED delivery crash: Awake committed 6, replay duplicates 6, delivered 6')

    def test_6_sigkill_during_backup_publish_leaves_partial_directory(self):
        # Synthetic required Awake schema and real outbox file, no real service.
        awake = self.base / 'awake-source' / 'awake.sqlite3'
        awake.parent.mkdir()
        with sqlite3.connect(awake) as db:
            for table in ('control','evidence','questions','ticks','ledger'):
                db.execute(f'CREATE TABLE {table} (id TEXT PRIMARY KEY)')
        dest = self.base / 'backup' / 'snap'
        def child():
            import atmosphere_recovery as r
            original_replace = r.os.replace
            hit = 0
            def kill_after_first(source, target):
                nonlocal hit
                original_replace(source,target)
                hit += 1
                if hit == 1:
                    os._exit(75)
            with patch.object(r.os, 'replace',kill_after_first):
                create_snapshot(awake_db=awake, outbox_db=self.path, archive_dir=dest, now=NOW)
        self.assertEqual(die_in_child(child), 75)
        self.assertTrue(dest.exists())
        self.assertEqual(len(list(dest.iterdir())), 1)
        with self.assertRaisesRegex(FileExistsError, 'archive-already-exists'):
            create_snapshot(awake_db=awake, outbox_db=self.path, archive_dir=dest, now=NOW)
        print('OBSERVED publish crash: visible partial backup folder; same target cannot be retried')


if __name__ == '__main__':
    unittest.main()
