"""Synthetic compatibility and interruption tests; never open live user stores."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from . import history as h
from .body_dialogue import DialogueBodyBridge
from .engine import AffectiveAgent, canonical, digest
from .test_body_dialogue import message
from examples.nasuraya_body_loop.host import BodyLoop
from unified_body_v2 import UnifiedBody

ROOT = Path(__file__).resolve().parents[2]


def row(snapshot, table, key, ledger='body.sqlite'):
    return next(r for r in snapshot['tables'][ledger][table] if r.get('key', r.get('id')) == key)


def edit_state(snapshot, key, change, ledger='body.sqlite'):
    target = row(snapshot, 'meta', key, ledger)
    state = h.envelope(target['value'])
    change(state)
    target['value'] = canonical(dict(value=state, sha256=digest(state)))


def files(folder):
    return {p.name: (p.stat().st_mode, p.read_bytes()) for p in folder.iterdir() if p.is_file()}


def write_bundle(path, snapshot):
    path.write_text(canonical(dict(value=snapshot, sha256=digest(snapshot))) + '\n')
    return digest(snapshot)


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        # Execute the actual pinned old bridge only to generate a synthetic test
        # fixture. Production recovery never loads code supplied by an archive.
        legacy_source = subprocess.check_output(['git', 'show',
            '8e952de53dbbb8c5c6a8f9d5620f9823e1c7932d:examples/nasuraya_affect/body_dialogue.py'], cwd=ROOT)
        assert hashlib.sha256(legacy_source).hexdigest() == '256eb4a31f5eefa3395f1735a1587c0aca7572e8c774a77e0febbf362694cbdc'
        legacy_path = cls.root / 'body_dialogue.py'
        legacy_path.write_bytes(legacy_source)
        spec = importlib.util.spec_from_file_location('examples.nasuraya_affect._legacy_history_fixture', legacy_path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        cls.legacy_class = module.DialogueBodyBridge
        for name, bridge_class, stage in (
            ('current', DialogueBodyBridge, None), ('legacy', cls.legacy_class, None),
            ('after-native', DialogueBodyBridge, 'native'),
            ('after-learning', DialogueBodyBridge, 'learning'),
            ('unknown', DialogueBodyBridge, 'unknown'),
            ('reserved', DialogueBodyBridge, 'reserved')):
            folder = cls.root / name; folder.mkdir()
            with BodyLoop.start(folder/'body.sqlite', max_actions=3) as body, AffectiveAgent(folder/'affect.sqlite') as affect:
                bridge = bridge_class.enable(body, affect)
                if stage == 'native':
                    with patch.object(bridge, '_finish', side_effect=OSError('lost dialogue result')):
                        with unittest.TestCase().assertRaises(OSError): bridge.receive(message())
                elif stage == 'learning':
                    save = bridge._save
                    def crash(state):
                        if state['intents']['one']['result'] is not None:
                            raise OSError('lost final save')
                        return save(state)
                    with patch.object(bridge, '_save', side_effect=crash):
                        with unittest.TestCase().assertRaises(OSError): bridge.receive(message())
                elif stage == 'unknown':
                    with patch.object(body, 'step', side_effect=OSError('connection lost')):
                        with unittest.TestCase().assertRaises(OSError): bridge.receive(message())
                elif stage == 'reserved':
                    with patch.object(affect, 'step', side_effect=OSError('planning lost')):
                        with unittest.TestCase().assertRaises(OSError): bridge.receive(message())
                else:
                    bridge.receive(message())
                    bridge.receive(message('two'))
                    bridge.receive(message('reflection', 'reflect'))
        cls.snapshots = {p.name: h.capture(p) for p in cls.root.iterdir() if p.is_dir()}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def snapshot(self, name='current'):
        return deepcopy(self.snapshots[name])

    def validated(self, name='current'):
        report = h.inspect(self.snapshot(name))
        self.assertEqual(report['status'], 'validated_read_only', report)
        return report

    def blocked(self, snapshot, reason):
        report = h.inspect(snapshot)
        self.assertEqual(report['status'], 'archive_only')
        self.assertEqual(report['records'], [])
        self.assertIn(reason, ' '.join(report['reasons']))

    def test_actual_legacy_source_recovers_without_fabricating_forecasts(self):
        report = self.validated('legacy')
        self.assertEqual(report['source_commit'], 'a6e6f451e4383383082a536b19966755a9ac09a1')
        one = h.trace(report, 'one')
        self.assertIsNotNone(one['outcome'])
        self.assertIsNone(one['forecast'])
        self.assertIsNone(one['prediction'])
        self.assertIsNone(one['stored_episode'])
        self.assertFalse(report['active_state_migration'])

    def test_current_episode_prediction_and_message_keep_distinct_provenance(self):
        one = h.trace(self.validated(), 'one')
        self.assertEqual(one['message_source'], 'conversation://one')
        self.assertEqual(one['appraisal_kind'], 'caller_authored_interpretation')
        self.assertEqual(one['outcome']['source'], one['stored_episode']['source'])
        self.assertEqual(one['outcome']['source'], one['prediction']['source'])
        self.assertNotIn('actual', one['forecast'])
        self.assertIn('actual', one['prediction'])

    def test_completed_receipt_after_disconnect_is_read_without_learning(self):
        one = h.trace(self.validated('after-native'), 'one')
        self.assertEqual(one['status'], 'receipt_recovered_not_reexecuted')
        self.assertIsNotNone(one['outcome'])
        self.assertIsNone(one['prediction'])
        self.assertIsNone(one['stored_episode'])
        self.assertEqual(one['learning_updates'], 0)

    def test_completed_learning_before_lost_bridge_commit_is_preserved_once(self):
        report = self.validated('after-learning')
        one = h.replay(report, message())
        self.assertIsNotNone(one['stored_episode'])
        self.assertEqual(one['this_call_body_cycles'], 0)
        self.assertEqual(one, h.replay(report, message()))

    def test_unknown_outcome_is_never_reexecuted(self):
        report = self.validated('unknown')
        self.assertEqual(h.trace(report, 'one')['status'], 'unresolved_do_not_execute')
        with self.assertRaisesRegex(h.HistoryBlocked, 'unresolved'):
            h.replay(report, message())

    def test_reserved_before_planning_stays_unresolved(self):
        one = h.trace(self.validated('reserved'), 'one')
        self.assertIsNone(one['outcome'])
        self.assertEqual(one['status'], 'unresolved_do_not_execute')

    def test_reflection_preserves_no_body_result(self):
        one = h.trace(self.validated(), 'reflection')
        self.assertEqual(one['status'], 'completed')
        self.assertIsNone(one['outcome'])

    def test_readers_have_no_body_or_learning_side_effects(self):
        folder = self.root/'current'; before = files(folder)
        with patch.object(BodyLoop, 'step', side_effect=AssertionError('execution forbidden')), \
             patch.object(UnifiedBody, 'cycle', side_effect=AssertionError('execution forbidden')), \
             patch.object(AffectiveAgent, 'step', side_effect=AssertionError('learning forbidden')):
            report = h.inspect(h.capture(folder))
            h.replay(report, message()); h.trace(report, 'one'); h.recall(report, ['body'])
        self.assertEqual(before, files(folder))

    def test_duplicate_ids_in_distinct_sessions_are_namespaced(self):
        a = h.trace(self.validated(), 'one')
        b = h.trace(self.validated('legacy'), 'one')
        self.assertNotEqual(a['historical_id'], b['historical_id'])
        self.assertEqual(a['message_source'], b['message_source'])

    def test_conflicting_replay_and_unknown_id_never_fall_back_to_execution(self):
        report = self.validated()
        with self.assertRaisesRegex(h.HistoryBlocked, 'conflicting'):
            h.replay(report, dict(message(), text='different'))
        with self.assertRaisesRegex(h.HistoryBlocked, 'unknown historical'):
            h.replay(report, message('new'))

    def test_unrelated_recall_is_empty(self):
        self.assertEqual(h.recall(self.validated(), ['unrelated'])['records'], [])

    def test_future_hash_or_schema_requires_an_explicit_adapter(self):
        for key, value in (('source_hash', 'f'*64), ('schema', 'nasuraya-dialogue-body/2')):
            s = self.snapshot(); edit_state(s, h.KEY, lambda state: state.update({key: value}))
            self.blocked(s, 'unsupported dialogue source/version')

    def test_corrupt_envelope_is_not_repaired(self):
        s = self.snapshot(); r = row(s, 'meta', h.KEY)
        r['value'] = r['value'].replace('"enabled":true', '"enabled":false')
        self.blocked(s, 'checksum mismatch')

    def test_foreign_affect_pair_rejected(self):
        s = self.snapshot()
        r = row(s, 'meta', h.KEY, 'affect.sqlite')
        b = json.loads(r['value']); b['body_path'] += '-foreign'; r['value'] = canonical(b)
        self.blocked(s, 'paired-ledger binding mismatch')

    def test_native_request_fingerprint_checked(self):
        s = self.snapshot(); r = row(s, 'decisions', 'dialogue-body:one')
        v = json.loads(r['record']); v['request']['execution']['duration_s'] = .2
        r['record'] = canonical(v)
        self.blocked(s, 'native identity/fingerprint mismatch')

    def test_checkpoint_tampering_rejected(self):
        s = self.snapshot(); r = row(s, 'decisions', 'dialogue-body:one')
        v = json.loads(r['record']); v['actual_outcome']['body_checkpoint']['payload']['revision'] = 999
        r['record'] = canonical(v)
        self.blocked(s, 'whole-body checksum mismatch')

    def test_duplicated_episode_rejected_even_with_recomputed_envelope(self):
        s = self.snapshot()
        edit_state(s, h.EXPERIENCE_KEY, lambda v: v['episodes'].append(deepcopy(v['episodes'][0])))
        self.blocked(s, 'duplicate experience episode')

    def test_receipt_provenance_cannot_be_relabelled(self):
        s = self.snapshot()
        edit_state(s, h.EXPERIENCE_KEY, lambda v: v['episodes'][0].update(source='native-decision://foreign'))
        self.blocked(s, 'experience provenance mismatch')

    def test_forecast_error_and_observation_validated_against_receipt(self):
        s = self.snapshot()
        edit_state(s, h.EXPERIENCE_KEY, lambda v: v['intents']['one']['result']['prediction'].update(mean_absolute_error=.99))
        self.blocked(s, 'prediction error mismatch')

    def test_forecast_history_digest_cannot_be_relabelled(self):
        s = self.snapshot()
        def tamper(v):
            for forecast in (v['intents']['two']['plan']['prediction'], v['intents']['two']['result']['prediction']):
                forecast['history_sha256'] = '0'*64
        edit_state(s, h.EXPERIENCE_KEY, tamper)
        self.blocked(s, 'forecast history checksum mismatch')

    def test_experience_cached_receipt_cannot_be_relabelled(self):
        s = self.snapshot()
        edit_state(s, h.EXPERIENCE_KEY, lambda v: v['intents']['one']['result']['native_receipt'].update(actual_action='protect'))
        self.blocked(s, 'experience cached receipt mismatch')

    def test_dialogue_result_provenance_cannot_be_promoted(self):
        s = self.snapshot()
        edit_state(s, h.KEY, lambda v: v['intents']['one']['result']['provenance'].update(appraisal='verified_user_belief'))
        self.blocked(s, 'dialogue result provenance mismatch')

    def test_extra_schema_columns_are_not_silently_accepted(self):
        s = self.snapshot(); s['tables']['affect.sqlite']['events'][0]['future'] = True
        self.blocked(s, 'unknown affect event columns')

    def test_forecast_cannot_use_its_own_future_receipt(self):
        s = self.snapshot()
        def tamper(v):
            for forecast in (v['intents']['one']['plan']['prediction'], v['intents']['one']['result']['prediction']):
                forecast['history_ids'] = ['one']
        edit_state(s, h.EXPERIENCE_KEY, tamper)
        self.blocked(s, 'forecast history must precede')

    def test_native_checkpoint_chain_is_checked(self):
        s = self.snapshot(); r = row(s, 'decisions', 'dialogue-body:two')
        v = json.loads(r['record']); v['request']['evidence'][0]['source_sha256'] = 'f'*64
        r['record'] = canonical(v)
        self.blocked(s, 'native checkpoint chain mismatch')

    def test_appraisal_cannot_be_promoted_or_changed(self):
        s = self.snapshot()
        edit_state(s, h.KEY, lambda v: v['intents']['one']['event']['appraisal'].update(certainty=.5))
        self.blocked(s, 'message/event provenance mismatch')

    def test_missing_receipt_is_not_reconstructed_from_message_result(self):
        s = self.snapshot(); s['tables']['body.sqlite']['decisions'] = []
        self.blocked(s, 'runtime differs from initial checkpoint without a receipt')

    def test_new_history_module_does_not_change_v03_active_contract(self):
        folder = self.root/'current'
        with BodyLoop(folder/'body.sqlite') as body, AffectiveAgent(folder/'affect.sqlite') as affect:
            bridge = DialogueBodyBridge(body, affect); before = bridge.status()
            result = bridge.receive(message())
            self.assertEqual(result['this_call_body_cycles'], 0)
            self.assertEqual(bridge.status(), before)

    def test_export_cannot_add_files_to_original_session(self):
        folder = self.root/'current'; before = files(folder)
        with self.assertRaisesRegex(h.HistoryBlocked, 'outside the source'):
            h.export_history(folder, folder/'archive.json')
        self.assertEqual(files(folder), before)

    def test_duplicate_json_and_nonfinite_values_rejected(self):
        for raw in ('{"a":1,"a":2}', '{"a":NaN}'):
            with self.assertRaises(h.HistoryBlocked): h.strict_json(raw)

    def test_external_archive_pin_detects_recomputed_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'archive.json'; s = self.snapshot(); pin = write_bundle(p, s)
            s['original_location'] += '-tampered'; write_bundle(p, s)
            with self.assertRaisesRegex(h.HistoryBlocked, 'pinned export'):
                h.load_history(p, pin)

    def test_unknown_version_export_remains_archive_only(self):
        s = self.snapshot(); edit_state(s, h.KEY, lambda v: v.update(source_hash='a'*64))
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'archive.json'
            with patch.object(h, 'capture', return_value=s): report = h.export_history('unused', p)
            self.assertEqual(report['report']['status'], 'archive_only')
            with self.assertRaisesRegex(h.HistoryBlocked, 'archive-only'):
                h.load_history(p, report['archive_sha256'])
            self.assertEqual(h.envelope(p.read_text()), s)

    def test_failed_atomic_publication_does_not_leave_partial_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'archive.json'
            with patch.object(h.os, 'link', side_effect=OSError('connection/process interrupted')):
                with self.assertRaises(OSError): h.export_history(self.root/'current', p)
            self.assertFalse(p.exists()); self.assertEqual(list(Path(tmp).iterdir()), [])
            report = h.export_history(self.root/'current', p)
            self.assertEqual(h.load_history(p, report['archive_sha256'])['status'], 'validated_read_only')
            before = p.read_bytes()
            with self.assertRaises(FileExistsError): h.export_history(self.root/'current', p)
            self.assertEqual(before, p.read_bytes())

    def test_capture_refuses_active_writer(self):
        with BodyLoop(self.root/'current'/'body.sqlite'):
            with self.assertRaises(BlockingIOError): h.capture(self.root/'current')

    def test_capture_detects_a_concurrent_uncooperative_change(self):
        original = h._source_bytes; calls = 0
        def changed(folder):
            nonlocal calls
            calls += 1; result = original(folder)
            if calls == 2: result['body.sqlite'] += b'x'
            return result
        with patch.object(h, '_source_bytes', side_effect=changed):
            with self.assertRaisesRegex(h.HistoryBlocked, 'source changed'):
                h.capture(self.root/'current')

    def test_symlink_source_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'alias'; p.symlink_to(self.root/'current', target_is_directory=True)
            with self.assertRaises(h.HistoryBlocked): h.capture(p)

    def test_cold_cli_export_replay_and_recall_leave_source_unchanged(self):
        folder = self.root/'legacy'; before = files(folder)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'history.json'; msg = Path(tmp)/'message.json'; msg.write_text(canonical(message()))
            def command(*args):
                result = subprocess.run([sys.executable, '-m', 'nasuraya', 'dialogue', *map(str,args)],
                    cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return json.loads(result.stdout)
            exported = command('history-export', '--session-dir', folder, '--output', out)
            common = ('--archive', out, '--expected-sha256', exported['archive_sha256'])
            a = command('history-replay', *common, '--message', msg)
            b = command('history-replay', *common, '--message', msg)
            self.assertEqual(a, b); self.assertEqual(a['this_call_body_cycles'], 0)
            recalled = command('history-recall', *common, '--cue', 'body')
            self.assertEqual(len(recalled['records']), 3)
        self.assertEqual(before, files(folder))

    def test_abrupt_process_exit_recovers_committed_wal_without_touching_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/'crashed'; folder.mkdir()
            script = '''
import os,sys
from pathlib import Path
from examples.nasuraya_body_loop.host import BodyLoop
from examples.nasuraya_affect.engine import AffectiveAgent
from examples.nasuraya_affect.body_dialogue import DialogueBodyBridge
from examples.nasuraya_affect.test_body_dialogue import message
p=Path(sys.argv[1]); b=BodyLoop.start(p/'body.sqlite'); a=AffectiveAgent(p/'affect.sqlite')
DialogueBodyBridge.enable(b,a).receive(message())
os._exit(0)
'''
            child = subprocess.run([sys.executable, '-c', script, str(folder)], capture_output=True, text=True)
            self.assertEqual(child.returncode, 0, child.stderr)
            before = files(folder)
            self.assertGreater(len(before['body.sqlite-wal'][1]), 0)
            report = h.inspect(h.capture(folder))
            self.assertEqual(report['status'], 'validated_read_only', report)
            self.assertEqual(h.replay(report, message())['this_call_body_cycles'], 0)
            self.assertEqual(before, files(folder))
