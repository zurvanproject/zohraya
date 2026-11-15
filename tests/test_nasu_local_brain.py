"""Offline local-brain contracts. No Ollama download, network or VPS required."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "tools" / "nasu_local_brain.py"
SPEC = importlib.util.spec_from_file_location("nasu_local_brain", SOURCE)
brain = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(brain)


class FakeResponse:
    status = 200
    def __init__(self, payload):
        self.payload = json.dumps(payload, ensure_ascii=False).encode()
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    def read(self, size):
        return self.payload[:size]


class QwenContract(unittest.TestCase):
    def test_persian_json_response_disables_reasoning(self):
        captured = {}
        data = {
            "done": True,
            "thinking": "This shouldn't appear in a report.",
            "response": json.dumps({
                "observation": "در حافظه ۶۰ رویداد ثبت شده است.",
                "testable_question": "آیا تعداد رویدادها در شش ساعت بعد افزایش می‌یابد؟",
                "next_safe_step": "فقط شمارندهٔ بعدی را با گزارش پیشین مقایسه کن."
            }, ensure_ascii=False)
        }
        def responder(request, timeout):
            captured.update(json.loads(request.data))
            return FakeResponse(data)
        with patch.object(brain.urllib.request, 'urlopen', responder):
            text = brain.infer({"awake": {"state": "test"}}, [])
        self.assertIn('/no_think', captured['prompt'])
        self.assertEqual(captured['format'], 'json')
        self.assertIs(captured['think'], False)
        self.assertGreaterEqual(captured['options']['num_predict'], 350)
        self.assertIn('مشاهده:', text)
        self.assertIn('پرسش قابل‌آزمایش:', text)
        self.assertIn('گام بعدی امن:', text)
        self.assertNotIn('This shouldn', text)

    def test_english_preamble_is_rejected(self):
        with patch.object(brain.urllib.request, 'urlopen',
                          return_value=FakeResponse({"done": True,
                                                     "response": "Okay, let me think..."})):
            with self.assertRaisesRegex(RuntimeError, 'JSON'):
                brain.infer({}, [])

    def test_english_values_are_rejected(self):
        payload = {"done": True, "response": json.dumps({
            "observation": "Observed a count of 60",
            "testable_question": "Test what changes?",
            "next_safe_step": "Do nothing"
        })}
        with patch.object(brain.urllib.request, 'urlopen',
                          return_value=FakeResponse(payload)):
            with self.assertRaisesRegex(RuntimeError, 'Persian'):
                brain.infer({}, [])

    def test_missing_field_is_rejected(self):
        payload = {"done": True, "response": '{"observation":"سلام"}'}
        with patch.object(brain.urllib.request, 'urlopen',
                          return_value=FakeResponse(payload)):
            with self.assertRaises(RuntimeError):
                brain.infer({}, [])


class LocalJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        folder = self.home / 'awake-stage'
        folder.mkdir()
        self.awake = folder / 'awake.sqlite3'
        with sqlite3.connect(self.awake) as db:
            for name, count in (("evidence", 3), ("questions", 2),
                                ("ticks", 4), ("ledger", 5)):
                db.execute(f'CREATE TABLE {name} (id INTEGER)')
                db.executemany(f'INSERT INTO {name} VALUES (?)',
                               [(i,) for i in range(count)])
            db.execute('CREATE TABLE control (name TEXT, value TEXT)')
            db.execute("INSERT INTO control VALUES ('paused', '0')")

    def test_read_only_awake(self):
        before = self.awake.stat().st_size
        snapshot = brain.awake_snapshot(self.home)
        self.assertEqual(snapshot['counts']['ticks'], 4)
        self.assertFalse(snapshot['paused'])
        self.assertEqual(before, self.awake.stat().st_size)

    def test_focus_import_is_historical_only(self):
        folder = self.home / 'focus-20261115-123627' / 'lesson'
        folder.mkdir(parents=True)
        (folder / 'focused_review.json').write_text(json.dumps({
            'schema': 'nasuraya.focus/setar-three-stage/1',
            'overall': 'setar_lesson_verified_with_evidence_review',
            'run_id': 'first-focus',
            'setar': {'state': 'completed', 'updates_total': 2878,
                      'simulated_seconds': 11.2},
            'review': [{}, {'synthetic_audio_errors': {'pitch_cents_mae': 1.23}}, {}],
            'ritual': {'state': 'not_supplied'}
        }))
        result = brain.focus_snapshot(self.home)
        self.assertEqual(result['updates_total'], 2878)
        self.assertEqual(result['source'], 'prior locally generated evidence report, no new practice')

    def test_journal_does_not_double_count_same_slot(self):
        journal = self.home / 'local-brain'
        with patch.object(brain.os, 'geteuid', return_value=1001), \
             patch.object(brain, 'infer', return_value='مشاهده: سالم\nپرسش: تغییر؟\nگام امن: مشاهده'), \
             patch.object(brain, 'awake_snapshot', return_value={'state': 'read_only_snapshot'}), \
             patch.object(brain, 'focus_snapshot', return_value={'state': 'not_found'}):
            first = brain.run(home=self.home, folder=journal)
            second = brain.run(home=self.home, folder=journal)
        self.assertEqual(first['status'], 'recorded')
        self.assertEqual(second['status'], 'already_recorded')
        self.assertEqual(brain.status(journal)['reports'], 1)


if __name__ == '__main__':
    unittest.main()
