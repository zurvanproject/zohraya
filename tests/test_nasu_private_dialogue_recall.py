import unittest

from tools import nasu_private_dialogue as chat


class RecallTests(unittest.TestCase):
    def setUp(self):
        self.db = chat.open_dialogue(":memory:")
        self.addCleanup(self.db.close)

    def add(self, user, reply="پاسخ"):
        self.db.execute("INSERT INTO turns(message,reply,stance) VALUES(?,?,?)",
                        (user, reply, "respond"))

    def filler(self):
        for _ in range(3):
            self.add("موضوع دیگر")

    def test_variants_both_directions(self):
        self.add("نام من كيان است")
        self.add("نام دیگر کیان است")
        self.filler()
        for query in ("کیان", "كيان", 'كيان OR "'):
            older = chat.memories(self.db, query)[:2]
            self.assertEqual([e["user"] for e in older],
                             ["نام من كيان است", "نام دیگر کیان است"])

    def test_user_before_assistant_and_no_duplicate(self):
        self.add("کلید فانوس", "فانوس")
        self.add("الف", "فانوس فانوس فانوس")
        self.add("ب", "فانوس فانوس فانوس")
        self.filler()
        rows = chat.memories(self.db, "فانوس")
        self.assertEqual(rows[0]["user"], "کلید فانوس")
        self.assertEqual(len(rows), 5)
        self.assertEqual(len(set(x["turn"] for x in rows)), 5)

    def test_two_primary_matches_cannot_be_displaced(self):
        self.add("فانوس نخست")
        self.add("فانوس دوم")
        self.add("الف", "فانوس فانوس فانوس")
        self.filler()
        self.assertEqual([x["turn"] for x in chat.memories(self.db, "فانوس")],
                         [1, 2, 4, 5, 6])

    def test_fallback_preserves_assistant_recall(self):
        self.add("الف", "فانوس")
        self.filler()
        self.assertEqual([x["turn"] for x in chat.memories(self.db, "فانوس")],
                         [1, 2, 3, 4])

    def test_bounded_query(self):
        query = chat.recall_query(" ".join(f"کیا{i}" for i in range(30)))
        self.assertLessEqual(len(query.split(" OR ")), 64)
        self.assertEqual(chat.recall_query('"* -'), "")


if __name__ == "__main__":
    unittest.main()
