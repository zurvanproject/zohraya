"""Host-only absence review; no network and no new authorization."""
import unittest
import json
from pathlib import Path
from types import SimpleNamespace

from examples.nasuraya_agent_loop.api_recovery import APIRecovery, RecoveryBlocked
from .creation_reconciliation import resolve_empty_project
from . import test_api_recovery as fixtures


class CreationTests(unittest.TestCase):
    setUp = fixtures.RecoveryTests.setUp
    reopen = fixtures.RecoveryTests.reopen

    def reserve(self):
        APIRecovery(self.host, 'simulator', 'resume')
        self.loop.engine.db.execute("INSERT INTO body_api_transport VALUES('recovery','simulator','creating',NULL,NULL,NULL)")
        self.pages = []
        def listing(**kwargs):
            self.assertEqual(kwargs, dict(limit=100, order='desc', timeout=15))
            self.pages.append(kwargs)
            return dict(data=[], has_more=False)
        self.sessions = SimpleNamespace(list=listing)

    def resolve(self, **kw):
        return resolve_empty_project(self.host, self.sessions,
            previous_request_finished=True, exclusive_project_writer=True, **kw)

    def assert_reserved(self):
        row = self.loop.engine.db.execute("SELECT state FROM body_api_transport WHERE run_id='recovery'").fetchone()
        self.assertEqual(row[0], 'creating')

    def test_no_host_attestation_means_no_requests(self):
        self.reserve()
        for kw in ({}, dict(previous_request_finished=True),
                   dict(previous_request_finished=1, exclusive_project_writer=True)):
            with self.assertRaises(RecoveryBlocked):
                resolve_empty_project(self.host, self.sessions, **kw)
        self.assertEqual(self.pages, [])
        self.assert_reserved()

    def test_two_complete_empty_reads_preserve_goal_budget_and_checkpoint(self):
        self.reserve()
        before = self.host.snapshot(), self.host.evaluate(), self.loop.config.copy()
        review = self.resolve()
        self.assertEqual(len(self.pages), 2)
        self.assertEqual(review['historical_creation_outcome'], 'not inferred')
        self.assertIsNone(APIRecovery(self.host, 'simulator', 'resume').saved)
        self.assertEqual(before, (self.host.snapshot(), self.host.evaluate(), self.loop.config))
        self.reopen()
        self.assertEqual(self.resolve(), review)

    def test_nonempty_incomplete_or_malformed_listing_keeps_reservation(self):
        self.reserve()
        for page in (dict(data=[dict(id='unrelated')], has_more=False),
                     dict(data=[], has_more=True), dict(data=[]),
                     dict(data=[], has_more=0), dict(has_more=False)):
            self.sessions.list = lambda **_: page
            with self.assertRaises(RecoveryBlocked): self.resolve()
            self.assert_reserved()

    def test_second_read_connection_failure_keeps_reservation(self):
        self.reserve()
        def listing(**_):
            self.pages.append(1)
            if len(self.pages) == 2: raise ConnectionError('synthetic interruption')
            return dict(data=[], has_more=False)
        self.sessions.list = listing
        with self.assertRaises(ConnectionError): self.resolve()
        self.assert_reserved()

    def test_known_session_cannot_be_cleared(self):
        self.reserve()
        APIRecovery(self.host, 'simulator', 'resume').session('known-session')
        with self.assertRaises(RecoveryBlocked): self.resolve()
        self.assertEqual(self.pages, [])

    def test_local_tool_receipt_blocks_absence_review(self):
        self.reserve()
        self.loop.engine.db.execute("INSERT INTO body_api_run_calls VALUES('synthetic-call','recovery')")
        with self.assertRaises(RecoveryBlocked): self.resolve()
        self.assertEqual(self.pages, [])
        self.assert_reserved()

    def test_review_retry_does_not_delete_a_later_creation_reservation(self):
        self.reserve()
        review = self.resolve()
        self.loop.engine.db.execute("INSERT INTO body_api_transport VALUES('recovery','simulator','creating',NULL,NULL,NULL)")
        self.assertEqual(self.resolve(), review)
        self.assertEqual(len(self.pages), 2)
        self.assert_reserved()

    def test_database_failure_rolls_back_review_and_reservation(self):
        self.reserve()
        self.loop.engine.db.execute("CREATE TRIGGER forbid_delete BEFORE DELETE ON body_api_transport BEGIN SELECT RAISE(ABORT,'synthetic storage failure'); END")
        with self.assertRaises(Exception): self.resolve()
        self.assert_reserved()
        self.assertIsNone(self.loop.engine.db.execute('SELECT * FROM body_api_creation_reviews').fetchone())

    def test_terminal_replay_check_rejects_unknown_creation(self):
        from .terminal_replay_check import check
        self.reserve()
        self.loop.close()
        with self.assertRaises(ValueError):
            check(self.path, 'recovery', Path(self.temp.name)/'replay')

    def test_terminal_replay_check_reads_completed_synthetic_goal_without_api(self):
        from .terminal_replay_check import check
        from examples.nasuraya_agent_loop.agents_api import run_api
        from examples.nasuraya_agent_loop.tests.test_agents_api import call, requires
        def events():
            for i in range(2):
                yield requires(call('observe_body', call_id='read-'+str(i)))
                yield requires(call('request_body_action',
                    dict(action='observe',duration_s=.1,
                         observed_checkpoint_sha256=self.host.snapshot()['checkpoint_sha256']),
                    call_id='action-'+str(i)))
            yield requires(call('evaluate_body', call_id='evaluate'))
            yield fixtures.ended()
        api = fixtures.SimulatedAPI(events)
        self.assertEqual(run_api(self.host,api.client,model='simulator')['status'],'completed')
        self.loop.close()
        output=Path(self.temp.name)/'replay'
        self.assertEqual(check(self.path,'recovery',output),0)
        self.assertFalse(json.loads((output/'summary.json').read_text())['fresh_process'])


if __name__ == '__main__': unittest.main()
