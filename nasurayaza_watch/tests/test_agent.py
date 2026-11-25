import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from datetime import datetime, timezone, timedelta
from nasurayaza_watch.agent import database, poll, critique, parse_interval, extract, error_poll
from nasurayaza_watch.health import healthy


def item(number=101, sha='a'*40, body='Independent tests for DreamerV3; 78 kg body'):
    return {'number': number, 'title': 'Audit future body forecast', 'body': body,
            'updated_at': '2026-10-30T18:49:47Z', 'state': 'open',
            'draft': True, 'merged_at': None, 'head': {'sha': sha}}


class Tests(unittest.TestCase):
    def test_interval(self):
        self.assertEqual(parse_interval('900'), 900)
        for bad in ('2', '0', 'banana', '86401'):
            with self.assertRaises(ValueError):
                parse_interval(bad)

    def test_audit_falsifiability_and_separate_body_models(self):
        q = critique(extract(item()))['questions']
        self.assertTrue(any('persistence' in x for x in q))
        self.assertTrue(any('195 kg' in x for x in q))
        self.assertTrue(any('draft' in x for x in q))

    def test_db_is_idempotent_but_records_new_sha(self):
        with TemporaryDirectory() as d:
            base = Path(d)
            con = database(base/'review.sqlite3')
            path = base/'status.json'
            self.assertEqual(poll(con,[item()],path)['new_reviews'],1)
            self.assertEqual(poll(con,[item()],path)['new_reviews'],0)
            self.assertEqual(poll(con,[item(sha='b'*40)],path)['new_reviews'],1)
            self.assertEqual(con.execute('SELECT count(*) FROM reviews').fetchone()[0],2)
            saved = json.loads(path.read_text())
            self.assertEqual(saved['repo_writes'],0)
            self.assertEqual(saved['model_api_calls'],0)
            con.close()

    def test_invalid_input_rejected_without_partial_insert(self):
        with TemporaryDirectory() as d:
            base = Path(d)
            con = database(base/'r.sqlite3')
            invalid = item(102); invalid['head']['sha']='evil'
            with self.assertRaises(ValueError):
                poll(con,[item(),invalid],base/'status.json')
            self.assertEqual(con.execute('SELECT count(*) FROM reviews').fetchone()[0],0)
            con.close()

    def test_failed_poll_is_explicit(self):
        with TemporaryDirectory() as d:
            base = Path(d)
            con=database(base/'r.sqlite3')
            error_poll(con,base/'status.json',ValueError('secret content'))
            self.assertNotIn('secret content',(base/'status.json').read_text())
            self.assertEqual(con.execute('SELECT problem FROM polls').fetchone()[0], 'ValueError')
            con.close()

    def test_health(self):
        with TemporaryDirectory() as d:
            path=Path(d)/'status.json'
            at=datetime.now(timezone.utc)
            path.write_text(json.dumps({'schema':'nasurayaza-watch/1','at':at.isoformat()}))
            self.assertTrue(healthy(path,900,at+timedelta(seconds=200)))
            self.assertFalse(healthy(path,900,at+timedelta(seconds=3000)))


if __name__ == '__main__':
    unittest.main()
