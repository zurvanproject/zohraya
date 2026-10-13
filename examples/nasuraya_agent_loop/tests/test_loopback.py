import importlib.util
import unittest

from examples.nasuraya_agent_loop.loopback import exercise


SDK_AVAILABLE=bool(importlib.util.find_spec("openai") and importlib.util.find_spec("httpx2"))


@unittest.skipUnless(SDK_AVAILABLE,"optional SDK dependencies not installed")
class LoopbackTests(unittest.TestCase):
    def test_full_http_sse_loop_completes(self):
        host,result=exercise("normal")
        self.assertEqual(result["status"],"completed")
        self.assertEqual(host.actions_used,5)
        self.assertEqual(result["cleanup_status"],"deleted")
        self.assertGreater(result["http_requests"],10)
        self.assertFalse(result["live_api_verified"])

    def test_duplicate_event_never_repeats_mutation(self):
        host,result=exercise("duplicate")
        self.assertEqual(result["status"],"completed")
        self.assertEqual(host.actions_used,5)
        self.assertIn("duplicate_call",[e["kind"] for e in host.journal.events])

    def test_incomplete_stream_keeps_partial_work_without_success(self):
        host,result=exercise("incomplete")
        self.assertEqual(result["status"],"stream_incomplete")
        self.assertEqual(host.state.completed_jobs,1)
        self.assertEqual(result["cleanup_status"],"deleted")

    def test_unknown_tool_is_rejected_over_http(self):
        host,result=exercise("unknown_tool")
        self.assertEqual(result["status"],"rejected")
        self.assertEqual(host.actions_used,0)

    def test_cleanup_error_is_visible_after_success(self):
        _,result=exercise("cleanup_error")
        self.assertEqual(result["status"],"completed")
        self.assertEqual(result["cleanup_status"],"failed")

    def test_unrelated_completed_turn_is_rejected_over_http(self):
        _,result=exercise("wrong_turn")
        self.assertEqual(result["status"],"rejected")
        self.assertTrue(result["evaluation"]["goal_reached"])
