"""Search releases its disposable SQLite index on every return path."""
import sqlite3
import unittest
from unittest.mock import patch

from nasuraya import history_search_worker as target

_REAL_CONNECT = sqlite3.connect


class TrackedConnection(sqlite3.Connection):
    """Keep explicit close observable instead of relying on garbage collection."""
    close_calls = 0
    fail_select = False

    def close(self):
        self.close_calls += 1
        return super().close()

    def execute(self, sql, *args, **kwargs):
        if self.fail_select and sql.startswith('SELECT rowid FROM messages'):
            raise sqlite3.OperationalError('injected search query failure')
        return super().execute(sql, *args, **kwargs)


class SearchResourceTests(unittest.TestCase):
    def setUp(self):
        self.connections = []
        self.report = dict(archive_sha256='a' * 64, records=[dict(
            historical_id='a' * 64 + '/one', id='one',
            message=dict(text='تعادل بدن'), message_source='conversation://one',
            appraisal_kind='caller_authored_interpretation', status='completed',
            outcome=None)])

    def tearDown(self):
        # Leave no handle open even when the regression is reproduced.
        for connection in self.connections:
            if connection.close_calls == 0:
                connection.close()

    def connect(self, *args, **kwargs):
        connection = _REAL_CONNECT(*args, factory=TrackedConnection, **kwargs)
        self.connections.append(connection)
        connection.fail_select = self.fail_select
        return connection

    def assert_closed(self):
        self.assertEqual(len(self.connections), 1)
        connection = self.connections[0]
        self.assertEqual(connection.close_calls, 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')

    def test_success_closes_disposable_index(self):
        self.fail_select = False
        with patch.object(target, 'load_history', return_value=self.report), \
             patch.object(target.sqlite3, 'connect', side_effect=self.connect):
            result = target.search('unused', 'a' * 64, 'تعادل')
        self.assertEqual(result['hits'][0]['message_id'], 'one')
        self.assert_closed()

    def test_sql_exception_closes_disposable_index(self):
        self.fail_select = True
        with patch.object(target, 'load_history', return_value=self.report), \
             patch.object(target.sqlite3, 'connect', side_effect=self.connect):
            with self.assertRaisesRegex(sqlite3.OperationalError, 'injected search query failure'):
                target.search('unused', 'a' * 64, 'تعادل')
        self.assert_closed()


if __name__ == '__main__':
    unittest.main()
