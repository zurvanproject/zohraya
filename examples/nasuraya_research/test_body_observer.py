"""Contract tests: no movement or policy update from research observation."""
import unittest
from .body_observer import observe_native_body


class ObserverContractTests(unittest.TestCase):
    def test_reads_native_fixture_without_mutation(self):
        from examples.nasuraya_self_model.evaluate import fixture
        body = fixture(0.5)
        before = body.checkpoint()
        observed = observe_native_body(body)
        self.assertEqual(before, body.checkpoint())
        self.assertEqual(observed["source_checkpoint_sha256"], before["sha256"])
        self.assertEqual(observed["native_cycles_executed"], 0)
        self.assertEqual(observed["action_requests_executed"], 0)
        self.assertEqual(observed["model_api_calls"], 0)
        self.assertEqual(len(observed["sensory"]["q"]), 6)
        self.assertEqual(len(observed["sensory"]["v"]), 6)

    def test_rejects_invalid_decision_evidence(self):
        from examples.nasuraya_self_model.evaluate import fixture
        body = fixture(0.5)
        with self.assertRaises(ValueError):
            observe_native_body(body, decisions=[{"correct": "guessed", "keep_withdraw": "KEEP"}])


if __name__ == "__main__":
    unittest.main()
