"""Offline deterministic regression contracts. No Qwen or VPS is contacted."""
import contextlib
import io
import json
import unittest
from unittest import mock

from tools import nasu_metacognition_holdout as m

class HoldoutTests(unittest.TestCase):
    def test_bank_balanced_and_precommitted(self):
        info = m.manifest()
        self.assertEqual(info["count"], 24)
        self.assertEqual(info["labels"], {"YES":8, "NO":8, "UNKNOWN":8})
        self.assertEqual(info, m.manifest())

    def test_rule_families_answer_yes_no_unknown(self):
        for rule, samples in m.FACTS:
            self.assertEqual([m.truth(rule, facts) for facts in samples],
                             ["YES","NO","UNKNOWN"])

    def test_prompt_inputs_never_include_oracle_label_or_id(self):
        ids = set()
        for item in m.bank():
            self.assertNotIn(item["id"], item["question"])
            self.assertNotIn("label=", item["question"])
            ids.add(item["id"])
        self.assertEqual(len(ids), 24)

    def test_perfect_model_scores_one_and_zero_error(self):
        expected = {row["question"]:row["label"] for row in m.bank()}
        result = m.evaluate(lambda q: {"answer":expected[q], "confidence":1.0})
        self.assertEqual(result["state"], "COMPLETE_FIXED_BANK")
        self.assertEqual(result["scoring"]["accuracy"], 1.0)
        self.assertEqual(result["scoring"]["ece_5bin"], 0)
        self.assertEqual(result["scoring"]["brier"], 0)

    def test_overconfident_yes_only_scores_one_third(self):
        result = m.evaluate(lambda q: {"answer":"YES","confidence":1.0})
        self.assertEqual(result["graded"], 24)
        self.assertAlmostEqual(result["scoring"]["accuracy"], 1/3, places=5)
        self.assertGreater(result["scoring"]["brier"], 0.6)

    def test_always_unknown_is_not_automatically_good(self):
        result = m.evaluate(lambda q: {"answer":"UNKNOWN","confidence":1.0})
        self.assertEqual(result["by_label"]["UNKNOWN"]["correct"], 8)
        self.assertEqual(result["by_label"]["YES"]["correct"], 0)
        self.assertEqual(result["by_label"]["NO"]["correct"], 0)

    def test_failed_request_is_not_silently_dropped(self):
        n = 0
        def fail_once(q):
            nonlocal n
            n += 1
            if n == 6:
                raise TimeoutError("private")
            return {"answer":"YES", "confidence":0.3}
        result = m.evaluate(fail_once)
        self.assertEqual(n, 24)
        self.assertEqual(result["failed_or_invalid"], 1)
        self.assertEqual(result["graded"], 23)
        self.assertEqual(result["state"], "INCOMPLETE_NOT_COMPARABLE")
        self.assertNotIn("private", json.dumps(result))

    def test_no_fake_success_when_every_response_malformed(self):
        r = m.evaluate(lambda q: {"answer":"garbage","confidence":1})
        self.assertEqual(r["graded"], 0)
        self.assertEqual(r["failed_or_invalid"], 24)
        self.assertIsNone(r["scoring"])

    def test_confidence_bounds_and_bool_rejected(self):
        for value in (True, -0.01, 1.1, "1", float("nan"), float("inf")):
            with self.subTest(value=str(value)), self.assertRaises(ValueError):
                m.validate({"answer":"YES", "confidence":value})

    def test_output_schema_is_exact(self):
        for item in ({"answer":"YES"},
                     {"answer":"YES","confidence":0.4,"secret":"never"},
                     {"answer":True,"confidence":0.4},
                     {"answer":"MAYBE","confidence":0.4}):
            with self.assertRaises(ValueError):
                m.validate(item)

    def test_local_model_called_once_with_bounded_prompt(self):
        observed = []
        def opener(request, *, timeout):
            observed.append((request, timeout))
            return io.BytesIO(json.dumps({
                "model":m.MODEL, "done":True,
                "response":json.dumps({"answer":"UNKNOWN","confidence":0.61}),
                "private":"never_log"}).encode())
        a = m.local_infer("Is X true?", opener=opener)
        self.assertEqual(a["answer"], "UNKNOWN")
        self.assertEqual(a["confidence"], 0.61)
        self.assertEqual(len(observed), 1)
        req, timeout = observed[0]
        self.assertEqual(timeout, m.TIMEOUT)
        self.assertEqual(req.full_url, m.URL)
        payload = json.loads(req.data)
        self.assertEqual(payload["model"], m.MODEL)
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["format"], "json")
        self.assertNotIn("never_log", json.dumps(a))

    def test_default_network_disabled_proxy_and_redirect(self):
        client = mock.Mock()
        client.open.return_value = io.BytesIO(json.dumps(
            {"model":m.MODEL,"done":True,
             "response":json.dumps({"answer":"NO","confidence":0.4})}).encode())
        with mock.patch.object(m.urllib.request, "build_opener", return_value=client) as build:
            m.local_infer("sample?")
        self.assertEqual(build.call_args.args[0].proxies, {})
        handler = build.call_args.args[1]
        self.assertIsInstance(handler, m._NoRedirect)
        fake = io.BytesIO()
        with self.assertRaises(ValueError):
            handler.redirect_request(None, fake, 302, "redirect", {}, "https://invalid.example")
        self.assertTrue(fake.closed)

    def test_reject_wrong_model_missing_done_and_oversized_response(self):
        samples = [
            b"x" * (m.MAX_BYTES+1),
            b"notjson",
            b"[]",
            json.dumps({"model":"other","done":True,"response":"{}"}).encode(),
            json.dumps({"model":m.MODEL,"done":False,"response":"{}"}).encode(),
        ]
        for sample in samples:
            with self.subTest(length=len(sample)), self.assertRaises(ValueError):
                m.local_infer("fixed?", opener=lambda *a,**k:io.BytesIO(sample))

    def test_manifest_cli_cannot_call_model(self):
        with mock.patch.object(m, "local_infer", side_effect=AssertionError("model invoked")):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                rc = m.main(["manifest"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.getvalue())["count"], 24)

    def test_live_mode_root_denied(self):
        with mock.patch.object(m.os,"geteuid",return_value=0), \
             mock.patch.object(m,"evaluate",side_effect=AssertionError("executed")):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                rc = m.main(["run-local"])
        self.assertEqual(rc,2)
        self.assertEqual(json.loads(out.getvalue())["state"],"ROOT_REFUSED")

    def test_no_implicit_run(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(m.main([]), 2)
        self.assertEqual(json.loads(out.getvalue())["state"], "USAGE_MANIFEST_OR_RUN_LOCAL")

    def test_bank_immutable_across_scoring(self):
        digest = m.manifest()["sha256"]
        m.evaluate(lambda q: {"answer":"NO","confidence":0.5})
        self.assertEqual(m.manifest()["sha256"], digest)

if __name__ == "__main__":
    unittest.main()
