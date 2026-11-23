import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools import nasu_private_dialogue as chat


class DialogueTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "private.sqlite3"
        self.db = chat.open_dialogue(self.path)
        self.addCleanup(lambda: self.db.close())
        self.contexts = []

    def infer(self, instruction, context, fields):
        if "signal" in fields:
            return {"signal": "loss" if "فقدان" in context["current_message"] else "none"}
        self.contexts.append(context)
        return {"stance": "disagree", "reply": "من با این برداشت موافق نیستم."}

    def test_affect_recall_and_stance_after_reopen(self):
        chat.turn(self.db, "خاطرهٔ فانوس و فقدان", self.infer, now=lambda: 1000.)
        self.assertEqual(self.contexts[-1]["suggestion"], chat.affect.POLICIES["reflect_repair"])
        self.db.close()
        self.db = chat.open_dialogue(self.path)
        for _ in range(4):
            chat.turn(self.db, "یک موضوع دیگر", self.infer, now=lambda: 1001.)
        chat.turn(self.db, "فانوس", self.infer, now=lambda: 1002.)
        recalled = self.contexts[-1]["conversation_history"][0]
        self.assertEqual(recalled["user"], "خاطرهٔ فانوس و فقدان")
        self.assertEqual(recalled["stance"], "disagree")
        state = json.loads(self.db.execute("SELECT state FROM checkpoint").fetchone()[0])
        self.assertGreater(state["affect"]["sadness"], 0)
        self.assertEqual(state["tick"], 6)

    def test_ollama_wire_contract_and_invalid_stance(self):
        def respond(req, timeout):
            payload = json.loads(req.data)
            self.assertEqual(req.full_url, chat.URL)
            self.assertEqual(payload["model"], chat.MODEL)
            self.assertFalse(payload["stream"])
            fields = payload["format"]["properties"]
            choice = {"signal": "loss"} if "signal" in fields else {"reply": "سلام", "stance": "invalid"}
            return io.BytesIO(json.dumps({"done": True, "response": json.dumps(choice)}).encode())

        with patch.object(chat.urllib.request, "build_opener") as opener:
            opener.return_value.open.side_effect = respond
            with self.assertRaisesRegex(ValueError, "invalid model choice"):
                chat.turn(self.db, "فقدان")
        self.assertEqual(opener.return_value.open.call_count, 2)
        self.assertIsNone(self.db.execute("SELECT state FROM checkpoint").fetchone())

    def test_failed_reply_rolls_back_both_records(self):
        def fail(instruction, context, fields):
            if "signal" in fields:
                return {"signal": "success"}
            raise TimeoutError()
        with self.assertRaises(TimeoutError):
            chat.turn(self.db, "پیام آزمایشی", fail)
        self.assertEqual(self.db.execute("SELECT count(*) FROM turns").fetchone()[0], 0)
        self.assertIsNone(self.db.execute("SELECT state FROM checkpoint").fetchone())
        chat.turn(self.db, "پیام آزمایشی", self.infer)
        self.assertEqual(self.contexts[-1]["conversation_history"], [])

if __name__ == "__main__":
    unittest.main()
