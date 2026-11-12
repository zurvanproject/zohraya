"""Development contracts, not independent human validation."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from examples.dios_nous.cognition import (
    AdvisoryGoalPlanner, CognitiveSession, EvidenceEvent, GoalOption,
    ORIGINS, PreferenceProfile,
)


class CognitiveContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db, self.anchor = self.root / 'memory.db', self.root / 'memory.anchor'

    def session(self):
        return CognitiveSession(self.db, self.anchor)

    def test_reused_modules_are_exact_pinned_project_blobs(self):
        root = Path(__file__).parent / 'reused'
        manifest = json.loads((root / 'provenance.json').read_text())
        for item in manifest['modules']:
            data = (root / item['local_path']).read_bytes()
            self.assertEqual(hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
                             item['git_blob_sha1'])

    def test_origin_does_not_change_evidence_or_verdict(self):
        with self.session() as session:
            session.append(EvidenceEvent(1, 1, 1, 'B', 1, 9))
            results = [session.assess(1, 1, 1, 'A', origin) for origin in sorted(ORIGINS)]
        self.assertEqual({r['verdict'] for r in results}, {'DISSENT'})
        self.assertTrue(all(r['opposing_roots'] == [9] and not r['execution_performed'] for r in results))
        self.assertTrue(all(r['confidence'] is None for r in results))

    def test_unknown_untrusted_scope_and_future(self):
        with self.session() as session:
            session.append(EvidenceEvent(1, 1, 1, 'A', 1, 1, False))
            session.append(EvidenceEvent(2, 2, 1, 'A', 1, 2))
            session.append(EvidenceEvent(3, 1, 1, 'A', 3, 3))
            result = session.assess(1, 1, 2, 'A')
            self.assertEqual(result['verdict'], 'ABSTAIN')
            self.assertEqual(result['supporting_roots'], [])

    def test_replay_conflict_and_revision(self):
        one = EvidenceEvent(1, 1, 1, 'A', 1, 1)
        with self.session() as session:
            self.assertEqual(session.append(one), 'new')
            self.assertEqual(session.append(one), 'replay')
            self.assertEqual(session.assess(1, 1, 1, 'A')['verdict'], 'SUPPORTED')
            with self.assertRaises(ValueError):
                session.append(EvidenceEvent(1, 1, 1, 'B', 1, 1))
            session.append(EvidenceEvent(2, 1, 1, 'B', 2, 2))
            revised = session.assess(1, 1, 2, 'A')
            self.assertTrue(revised['revised'])
            self.assertEqual(revised['previous_decision'], 'A')
            self.assertEqual(revised['decision'], 'B')
            self.assertTrue(revised['what_would_change_view'])
            session.append(EvidenceEvent(3, 1, 1, 'A', 2, 3))
            result = session.assess(1, 1, 2, 'A')
            self.assertEqual(result['verdict'], 'ABSTAIN')
            self.assertEqual(result['supporting_roots'], [3])
            self.assertEqual(result['opposing_roots'], [2])
            self.assertEqual(result['supporting_event_ids'], [3])
            self.assertEqual(result['opposing_event_ids'], [2])

    def test_history_query_does_not_rewind_live_view(self):
        with self.session() as session:
            session.append(EvidenceEvent(1, 1, 1, 'A', 1, 1))
            session.append(EvidenceEvent(2, 1, 1, 'B', 2, 2))
            session.assess(1, 1, 2, 'A')
            sealed = self.anchor.read_bytes()
            history = session.assess(1, 1, 1, 'A')
            self.assertTrue(history['historical_query'])
            self.assertFalse(history['revised'])
            self.assertEqual(self.anchor.read_bytes(), sealed)
            current = session.assess(1, 1, 2, 'A')
            self.assertEqual(current['previous_decision'], 'B')
            self.assertFalse(current['revised'])

    def test_same_root_contradiction_abstains(self):
        with self.session() as session:
            session.append(EvidenceEvent(1, 1, 1, 'A', 1, 1))
            session.append(EvidenceEvent(2, 1, 1, 'B', 1, 1))
            self.assertEqual(session.assess(1, 1, 1, 'A')['status'], 'abstain_provenance_conflict')

    def test_separate_interpreter_recovers_view(self):
        with self.session() as session:
            session.append(EvidenceEvent(1, 1, 1, 'B', 1, 1))
            session.assess(1, 1, 1, 'A')
        script = ('from examples.dios_nous.cognition import CognitiveSession; import json,sys; '
                  's=CognitiveSession(sys.argv[1],sys.argv[2]); '
                  'print(json.dumps(s.assess(1,1,1,"A"))); s.close()')
        result = subprocess.run([sys.executable, '-c', script, str(self.db), str(self.anchor)],
                                capture_output=True, text=True, check=True)
        recovered = json.loads(result.stdout)
        self.assertEqual(recovered['decision'], 'B')
        self.assertEqual(recovered['previous_decision'], 'B')
        self.assertFalse(recovered['revised'])

    def test_tampered_database_stops_read_and_reopen(self):
        with self.session() as session:
            session.append(EvidenceEvent(1, 1, 1, 'A', 1, 1))
            with sqlite3.connect(self.db) as connection:
                connection.execute("UPDATE evidence SET value='B'")
            with self.assertRaisesRegex(ValueError, 'integrity'):
                session.assess(1, 1, 1, 'A')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.session()

    def test_privacy_contract_rejects_strings_subclasses_and_duck_types(self):
        class Duck:
            def evidence(self):
                self.fail('method must not run')
        @dataclass(frozen=True)
        class PrivateProfile(PreferenceProfile):
            private_text: str = 'PRIVATE_CANARY'
        with self.session() as session:
            for event in (Duck(), EvidenceEvent('PRIVATE_CANARY', 1, 1, 'A', 1, 1),
                          EvidenceEvent(True, 1, 1, 'A', 1, 1)):
                with self.assertRaises(ValueError):
                    session.append(event)
        self.assertNotIn(b'PRIVATE_CANARY', self.db.read_bytes())
        planner = AdvisoryGoalPlanner(self.root/'goal', self.root/'goal.anchor', 1)
        with self.assertRaises(ValueError):
            planner.plan((GoalOption(1, 1, 1),), PrivateProfile())

    def test_goal_preferences_persistence_revision_and_stop(self):
        options = (GoalOption(1, 10, 9), GoalOption(2, 7, 1))
        path, anchor = self.root/'goal', self.root/'goal.anchor'
        planner = AdvisoryGoalPlanner(path, anchor, 1)
        self.assertEqual(planner.plan(options, PreferenceProfile(1, 0))['selected_goal'], 1)
        planner = AdvisoryGoalPlanner(path, anchor, 1)
        unchanged = planner.plan(options, PreferenceProfile(1, 1))
        self.assertEqual(unchanged['selected_goal'], 1)
        self.assertEqual(unchanged['preference_choice'], 2)
        self.assertTrue(unchanged['preference_changed'])
        revised = planner.plan(options, PreferenceProfile(1, 1), revise=True)
        self.assertEqual(revised['selected_goal'], 2)
        self.assertEqual(planner.plan((), PreferenceProfile(), stop=True)['selected_goal'], None)
        planner = AdvisoryGoalPlanner(path, anchor, 1)
        self.assertIsNone(planner.plan(options, PreferenceProfile(1, 0), revise=True)['selected_goal'])

    def test_goal_tie_and_tamper(self):
        path, anchor = self.root/'goal', self.root/'goal.anchor'
        planner = AdvisoryGoalPlanner(path, anchor, 1)
        self.assertEqual(planner.plan((GoalOption(10, 5, 1), GoalOption(2, 5, 1)),
                                     PreferenceProfile())['selected_goal'], 2)
        path.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            AdvisoryGoalPlanner(path, anchor, 1)


if __name__ == '__main__':
    unittest.main()
