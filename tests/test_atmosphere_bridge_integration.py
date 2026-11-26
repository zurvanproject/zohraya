"""End-to-end simulation for the Ubuntu Issue Bridge / ATMOSPHERE boundary."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import nasuraya_linux_bridge as bridge


class BridgeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.posts = []
        self.fail_next_post = False
        self.comments = []

    def api(self, method, path, data=None):
        if method == "GET" and path.endswith("/issues/212"):
            return {"state": "open", "user": {"login": "zurvanproject"}}
        if method == "GET" and "/comments?" in path:
            return self.comments
        if method == "POST" and path.endswith("/issues/212/comments"):
            if self.fail_next_post:
                self.fail_next_post = False
                raise ConnectionError("Simulated lost reply connection")
            self.posts.append(data["body"])
            return {"id": 999}
        raise AssertionError("Unexpected mocked GitHub request")

    @staticmethod
    def comment(number, body, sender="zurvanproject"):
        return {"id": number, "body": body, "user": {"login": sender}}

    def run_poll(self, dispatched):
        with (patch.object(bridge, "HOME", self.home),
              patch.object(bridge, "SEEN_PATH", self.home / "seen.json"),
              patch.object(bridge, "api", side_effect=self.api),
              patch.object(bridge, "dispatch", side_effect=dispatched)):
            bridge.poll()

    def test_injection_and_foreign_comments_never_reach_dispatch(self):
        self.comments = [
            self.comment(801, "nasu-linux: status"),
            self.comment(802, "before\nnasu-linux: sync"),
            self.comment(803, "nasu-linux: repo", "unknown-user"),
            self.comment(804, "nasu-linux: awake-activate"),
        ]
        calls = []
        def dispatch(action):
            calls.append(action)
            return "exit=0"
        self.run_poll(dispatch)
        self.assertEqual(calls, ["status"])
        self.assertEqual(len(self.posts), 2)
        self.assertTrue(any("ATMOSPHERE DENY" in p for p in self.posts))
        self.assertTrue(all("request_id=802" not in p for p in self.posts))

    def test_lost_post_does_not_execute_command_twice(self):
        self.comments = [self.comment(901, "nasu-linux: status")]
        self.fail_next_post = True
        calls = []
        def dispatch(action):
            calls.append(action)
            return "ONE-EXECUTION"
        with self.assertRaises(ConnectionError):
            self.run_poll(dispatch)
        self.run_poll(dispatch)
        self.assertEqual(calls, ["status"])
        self.assertEqual(len(self.posts), 1)
        self.assertIn("ONE-EXECUTION", self.posts[0])

    def test_status_result_persisted_before_post(self):
        self.comments = [self.comment(950, "nasu-linux: status")]
        calls = []
        self.run_poll(lambda action: calls.append(action) or "DONE")
        self.run_poll(lambda action: calls.append(action) or "SHOULD-NOT-RUN")
        self.assertEqual(calls, ["status"])
        self.assertEqual(len(self.posts), 1)


if __name__ == "__main__":
    unittest.main()
