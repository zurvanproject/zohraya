"""Tests for bounded offline prequential research and model hypothesis lab."""
import datetime as dt
import importlib.util
import pathlib
import tempfile
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / 'tools' / 'nasu_frontier_lab.py'
spec = importlib.util.spec_from_file_location('frontier', MODULE)
frontier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frontier)


def moment(day):
    return dt.datetime.fromisoformat(day + 'T14:00:00+00:00')


def sample(load):
    return {'load_1min':load,'memory_available_pct':92.0,'disk_available_pct':83.0}


class FrontierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = frontier.connect(pathlib.Path(self.temp.name)/'ledger.sqlite3')

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_first_day_is_observed_not_invented(self):
        result = frontier.run(self.db,now=moment('2026-11-18'),sample=sample(2.0),questioner=False)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['frontier'],'baseline')
        self.assertEqual(result['predictions_scored'],0)
        self.assertEqual(frontier.verify(self.db)['days'],1)

    def test_prequential_prediction_uses_prior_day_only(self):
        frontier.run(self.db,now=moment('2026-11-18'),sample=sample(2.0),questioner=False)
        result=frontier.run(self.db,now=moment('2026-11-19'),sample=sample(6.0),questioner=False)
        self.assertEqual(result['frontier'],'load_1min')
        row=self.db.execute('SELECT forecast_json,score_json FROM days WHERE day=?',('2026-11-19',)).fetchone()
        import json
        self.assertEqual(json.loads(row[0])['load_1min'],2.0)
        self.assertEqual(json.loads(row[1])['load_1min'],4.0)

    def test_repeated_day_is_idempotent(self):
        frontier.run(self.db,now=moment('2026-11-18'),sample=sample(1.0),questioner=False)
        result=frontier.run(self.db,now=moment('2026-11-18'),sample=sample(9.0),questioner=False)
        self.assertEqual(result['status'],'already_recorded')
        self.assertEqual(frontier.verify(self.db)['days'],1)

    def test_hypotheses_are_unverified_data(self):
        r=frontier.run(self.db,now=moment('2026-11-18'),sample=sample(1.0),
                       questioner=lambda *a:'Maybe CPU throttling?')
        self.assertEqual(r['model'],'UNVERIFIED_DRAFT')
        self.assertEqual(self.db.execute('SELECT model_question FROM days').fetchone()[0],
                         'Maybe CPU throttling?')

    def test_model_failure_does_not_break_monitor(self):
        def bad(*args):
            raise TimeoutError()
        r=frontier.run(self.db,now=moment('2026-11-18'),sample=sample(1.0),questioner=bad)
        self.assertEqual(r['model'],'unavailable:TimeoutError')
        self.assertEqual(frontier.verify(self.db)['status'],'ok')

    def test_out_of_order_day_cannot_corrupt_chain(self):
        frontier.run(self.db,now=moment('2026-11-19'),sample=sample(2.0),questioner=False)
        with self.assertRaisesRegex(ValueError,'Cannot backfill'):
            frontier.run(self.db,now=moment('2026-11-18'),sample=sample(1.0),questioner=False)
        self.assertEqual(frontier.verify(self.db)['days'],1)

    def test_tamper_detected(self):
        frontier.run(self.db,now=moment('2026-11-18'),sample=sample(1.0),questioner=False)
        self.db.execute("UPDATE days SET frontier='forged'")
        with self.assertRaisesRegex(ValueError,'Receipt mismatch'):
            frontier.verify(self.db)

    def test_reject_extra_data_fields(self):
        x=sample(1.0);x['secret']='x'
        with self.assertRaises(ValueError):
            frontier.run(self.db,now=moment('2026-11-18'),sample=x,questioner=False)

    def test_symlink_state_refused(self):
        root=pathlib.Path(self.temp.name)
        (root/'alias').symlink_to(root/'ledger.sqlite3')
        with self.assertRaisesRegex(ValueError,'Symlinked'):
            frontier.connect(root/'alias')

    def test_no_unverified_claim_after_bad_model_result(self):
        r=frontier.run(self.db,now=moment('2026-11-18'),sample=sample(1.0),
                       questioner=lambda *a:'')
        self.assertEqual(r['model'],'unavailable:ValueError')

    def test_reject_non_utc_timestamps(self):
        with self.assertRaisesRegex(ValueError,'UTC'):
            frontier.run(self.db, now=dt.datetime(2026,11,18), sample=sample(1.0),questioner=False)


if __name__ == '__main__':
    unittest.main()
