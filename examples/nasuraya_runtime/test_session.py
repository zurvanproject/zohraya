"""Integration contracts: real reused components, cold processes and faults."""
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from examples.dios_nous.unified.recovery import RecoveryAdvisor
from examples.dios_nous.unified.coordinator import workload_from_export
from examples.tadash_interoception.sensory import AfferentFrame
from . import adapters
from .__main__ import demo_frames
from .session import Session


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def create(self, name='run', **kwargs):
        return Session.create(self.root / name, **kwargs)


class SessionTests(Fixtures):
    def test_state_changes_behavior_without_labels(self):
        with self.create(max_actions=4) as session:
            receipts = [session.step('e' + str(i), demo_frames(i, x), expected_revision=i)
                        for i, x in enumerate((0, 0, .95, 0))]
            self.assertEqual([r['requested'] for r in receipts], ['recover', 'process_job', 'recover', 'recover'])
            self.assertFalse(receipts[1]['prediction']['occurred'])
            self.assertTrue(receipts[2]['prediction']['occurred'])
            self.assertFalse(receipts[3]['prediction']['occurred'])
            # Memory/load outlast the currently detected stimulus.
            self.assertGreater(receipts[3]['pressure'], .15)
            snap = session.snapshot()
            self.assertEqual(snap['sensory']['ticks'], 64)
            self.assertEqual(len(snap['sensory']['trace']), 12)
            self.assertEqual(snap['dios']['sensory_hypothesis_review']['stance'], 'ABSTAIN')
            self.assertEqual(snap['dios']['outcome_review']['evidence_review']['decision'], 'A')

    def test_fresh_process_resume_matches_uninterrupted(self):
        with self.create('reference') as reference, self.create('resumed') as resumed:
            for i, intensity in enumerate((0, 0, .95)):
                reference.step('e'+str(i), demo_frames(i, intensity), expected_revision=i)
            expected = reference.snapshot()
            resumed.step('e0', demo_frames(0, 0), expected_revision=0)
        for i, intensity in ((1, 0), (2, .95)):
            frame_path = self.root / ('frames' + str(i) + '.json')
            frame_path.write_text(json.dumps([asdict(f) for f in demo_frames(i, intensity)]))
            run = subprocess.run([sys.executable, '-m', 'examples.nasuraya_runtime', 'step',
                '--session', str(self.root / 'resumed'), '--frames', str(frame_path),
                '--event-id', 'e'+str(i), '--revision', str(i)],
                capture_output=True, text=True, encoding='utf-8', timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
        with Session(self.root / 'resumed') as resumed:
            self.assertEqual(resumed.snapshot(), expected)

    def test_duplicate_conflict_stale_writer_and_budget(self):
        with self.create(max_actions=1) as session, Session(self.root / 'run') as other:
            first = session.step('one', demo_frames(0, 0), expected_revision=0)
            self.assertEqual(other.step('one', demo_frames(0, 0), expected_revision=0), first)
            with self.assertRaisesRegex(ValueError, 'conflicting'):
                other.step('one', demo_frames(0, .9), expected_revision=0)
            with self.assertRaisesRegex(ValueError, 'stale'):
                other.step('other', demo_frames(1, 0), expected_revision=0)
        with Session(self.root / 'run') as resumed:
            with self.assertRaisesRegex(ValueError, 'budget'):
                resumed.step('two', demo_frames(1, 0), expected_revision=1)
            self.assertEqual(resumed.snapshot()['actions_used'], 1)

    def test_stop_persists_even_before_first_observation(self):
        with self.create(max_actions=0) as session:
            stop = session.stop()
            self.assertEqual(stop, session.stop())
        with Session(self.root / 'run') as resumed:
            with self.assertRaisesRegex(ValueError, 'stopped'):
                resumed.step('e', demo_frames(0, 0), expected_revision=1)
            snap = resumed.snapshot()
            self.assertEqual(snap['workload']['state'], 'HALTED')
            self.assertIsNone(snap['dios']['goal']['selected_goal'])
            self.assertEqual(snap['actions_used'], 0)

    def test_crash_after_commit_reconciles_without_reexecution(self):
        with self.create() as session:
            with patch.object(session, '_after_commit', side_effect=RuntimeError('injected crash')):
                with self.assertRaisesRegex(RuntimeError, 'injected crash'):
                    session.step('one', demo_frames(0, .9), expected_revision=0)
        self.assertFalse((self.root / 'run/projections/1').exists())
        with Session(self.root / 'run') as session:
            original = session.snapshot()
            receipt = session.step('one', demo_frames(0, .9), expected_revision=0)
            self.assertEqual(original, session.snapshot())
            self.assertEqual(receipt['revision'], 1)
            self.assertEqual(original['actions_used'], 1)
            self.assertTrue((self.root / 'run/projections/1').is_dir())

    def test_process_death_during_legacy_projection_is_recoverable(self):
        with self.create(): pass
        code = '''import os,sys
from examples.nasuraya_runtime.session import Session, CognitiveSession
from examples.nasuraya_runtime.__main__ import demo_frames
with Session(sys.argv[1]) as s:
    original=CognitiveSession.append
    def crash(self,event):
        original(self,event)
        os._exit(23)
    CognitiveSession.append=crash
    s.step('one',demo_frames(0,.9),expected_revision=0)
'''
        run = subprocess.run([sys.executable, '-c', code, str(self.root / 'run')], timeout=60)
        self.assertEqual(run.returncode, 23)
        with Session(self.root / 'run') as session:
            self.assertEqual(session.snapshot()['actions_used'], 1)
            session.step('one', demo_frames(0, .9), expected_revision=0)
            self.assertEqual(session.snapshot()['actions_used'], 1)
        # An abandoned generation is retained for diagnosis, never consumed.
        self.assertTrue(list((self.root / 'run/projections').glob('pending-*')))

    def test_projection_failure_before_action_does_not_commit(self):
        with self.create() as session:
            before = session.snapshot()
            with patch.object(session, '_project', side_effect=RuntimeError('projection unavailable')):
                with self.assertRaises(RuntimeError):
                    session.step('one', demo_frames(0, 0), expected_revision=0)
            self.assertEqual(before, session.snapshot())

    def test_invalid_frames_do_not_advance_state(self):
        with self.create() as session:
            before = session.snapshot()
            invalid = (AfferentFrame(.2, (0.,) * 6),)
            with self.assertRaisesRegex(ValueError, '0.1 second'):
                session.step('gap', invalid, expected_revision=0)
            with self.assertRaises(ValueError):
                session.step('label', ({'type': 'mechanical'},), expected_revision=0)
            self.assertEqual(before, session.snapshot())

    def test_event_corruption_and_published_projection_corruption_fail_closed(self):
        with self.create() as session:
            session.step('one', demo_frames(0, 0), expected_revision=0)
        goal = self.root / 'run/projections/1/goal.json'
        goal.write_text(goal.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'goal_integrity'):
            Session(self.root / 'run')
        with self.create('second') as session:
            session.step('one', demo_frames(0, 0), expected_revision=0)
        with sqlite3.connect(self.root / 'second/session.sqlite') as db:
            row = json.loads(db.execute('SELECT value FROM events').fetchone()[0])
            row['value']['receipt']['requested'] = 'changed'
            db.execute('UPDATE events SET value=?', (json.dumps(row),))
        with self.assertRaisesRegex(ValueError, 'integrity'):
            Session(self.root / 'second')

    def test_source_and_model_pins_fail_closed(self):
        with self.create(): pass
        with patch('examples.nasuraya_runtime.session.source_identity', return_value='0' * 64):
            with self.assertRaisesRegex(ValueError, 'implementation changed'):
                Session(self.root / 'run')
        with patch.object(adapters, 'MODEL_SHA', '0' * 64):
            with self.assertRaisesRegex(ValueError, 'decoder file mismatch'):
                Session(self.root / 'run')

    def test_visual_executes_and_unconnected_components_stay_explicit(self):
        with self.create() as session:
            before = session.snapshot()
            session.step('one', demo_frames(0, .95), expected_revision=0)
            after = session.snapshot()
            self.assertEqual(len(after['visual_plan']['options']), 3)
            self.assertNotEqual(before['visual_plan']['source_context_sha256'], after['visual_plan']['source_context_sha256'])
            self.assertFalse(after['visual_plan']['rendered'])
            self.assertEqual(after['visual_plan']['generator_calls'], 0)
            self.assertEqual(after['capabilities']['genome'], 'executed_fixed_fixture_not_mutated_or_applied_to_body')
            self.assertIn('no_live_connection', after['capabilities']['server_moltbook_desktop'])
            self.assertFalse(after['subjective_experience_established'])

    def test_creation_never_resets_existing_directory(self):
        with self.create() as session:
            session.stop()
        with self.assertRaises(FileExistsError): self.create()
        with Session(self.root / 'run') as session:
            self.assertTrue(session.snapshot()['stopped'])


@unittest.skipUnless(sys.platform == 'linux', 'native runtime requires Linux')
class NativeTests(Fixtures):
    # This class supplies two additional contracts, not the portable test suite.
    def test_native_palm_neural_affect_feedback_and_resume(self):
        with self.create(backend='native', max_actions=3) as session:
            start = session.snapshot()
            a = session.step('one', demo_frames(0, 0), expected_revision=0)
            b = session.step('two', demo_frames(1, 0), expected_revision=1)
            c = session.step('three', demo_frames(2, .95), expected_revision=2)
            end = session.snapshot()
            self.assertEqual([r['outcome']['executed'] for r in (a,b,c)], ['observe','walk','observe'])
            self.assertEqual(c['outcome']['touch']['kind'], 'declared_simulated_input')
            self.assertGreater(c['outcome']['touch']['value'], .1)
            self.assertGreater(end['body']['neural_ticks'], start['body']['neural_ticks'])
            # No emotional intensity change was observed in this fixture. The
            # real affect transition retains changed somatic feedback instead.
            self.assertEqual(end['body']['affect'], start['body']['affect'])
            self.assertNotEqual(end['body']['somatic_feedback'], start['body']['somatic_feedback'])
            self.assertNotEqual(end['body']['affect_state_sha'], start['body']['affect_state_sha'])
            self.assertAlmostEqual(end['body']['clock'] - start['body']['clock'], 4.8, places=7)
            self.assertLess(c['outcome']['audit']['energy_error_J'], 5e-5)
        with Session(self.root / 'run') as session:
            self.assertEqual(end, session.snapshot())
            self.assertEqual(session.step('three', demo_frames(2, .95), expected_revision=2), c)

    def test_native_protective_veto_revises_next_decision(self):
        with self.create(backend='native', fixture='sleep') as session:
            first = session.step('one', demo_frames(0, 0), expected_revision=0)
            self.assertEqual(first['outcome']['executed'], 'observe')
            second = session.step('two', demo_frames(1, 0), expected_revision=1)
            self.assertTrue(second['outcome']['body_veto'])
            self.assertEqual(second['outcome']['executed'], 'protect')
            self.assertEqual(session.snapshot()['dios']['outcome_review']['evidence_review']['verdict'], 'DISSENT')
            third = session.step('three', demo_frames(2, 0), expected_revision=2)
            self.assertTrue(third['candidate_outcome_dissent'])
            self.assertEqual(third['requested'], 'observe')
            self.assertEqual(third['outcome']['executed'], 'observe')
            self.assertEqual(session.snapshot()['dios']['outcome_review']['evidence_review']['decision'], 'A')
            # Success of observe does not authorize reattempting vetoed walk.
            fourth = session.step('four', demo_frames(3, 0), expected_revision=3)
            self.assertTrue(fourth['candidate_outcome_dissent'])
            self.assertEqual(fourth['requested'], 'observe')
            with Session(self.root / 'run') as cold:
                self.assertEqual(cold.snapshot()['dios']['action_reviews']['walk']['evidence_review']['decision'], 'B')

    def test_stale_native_workload_cannot_enable_motion(self):
        native = adapters.native_call({'checkpoint': None, 'fixture': 'normal'})
        advisor = RecoveryAdvisor()
        for tick in (0, 1):
            workload_from_export(advisor, native['export'], now_s=native['clock'], tick=tick)
        self.assertEqual(advisor.read()['state'], 'ACTIVE')
        workload_from_export(advisor, native['export'], now_s=native['clock'] + 6, tick=2)
        self.assertEqual(advisor.read()['state'], 'UNKNOWN')

    def test_native_worker_failure_rolls_back_and_can_retry(self):
        with self.create(backend='native', max_actions=1) as session:
            before = session.snapshot()
            with patch('examples.nasuraya_runtime.session.native_call', side_effect=RuntimeError('worker stopped')):
                with self.assertRaisesRegex(RuntimeError, 'worker stopped'):
                    session.step('one', demo_frames(0, 0), expected_revision=0)
            self.assertEqual(before, session.snapshot())
            session.step('one', demo_frames(0, 0), expected_revision=0)
            self.assertEqual(session.snapshot()['actions_used'], 1)

    def test_native_continues_identically_in_fresh_process(self):
        import shutil
        with self.create('first', backend='native') as session:
            session.step('one', demo_frames(0, 0), expected_revision=0)
        shutil.copytree(self.root / 'first', self.root / 'continued')
        with Session(self.root / 'first') as session:
            expected_receipt = session.step('two', demo_frames(1, .95), expected_revision=1)
            expected = session.snapshot()
        frames = self.root / 'native-frames.json'
        frames.write_text(json.dumps([asdict(f) for f in demo_frames(1, .95)]))
        run = subprocess.run([sys.executable, '-m', 'examples.nasuraya_runtime', 'step',
            '--session', str(self.root / 'continued'), '--frames', str(frames),
            '--event-id', 'two', '--revision', '1'],
            capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), expected_receipt)
        with Session(self.root / 'continued') as session:
            self.assertEqual(session.snapshot(), expected)


if __name__ == '__main__': unittest.main()
