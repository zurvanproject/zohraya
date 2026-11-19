"""No-network pilot contracts; synthetic outputs are not Qwen measurements."""
import contextlib
import io
import json
import unittest
from unittest import mock
from tools import nasu_metacognition_holdout as m

class PilotTests(unittest.TestCase):
    def test_fixed_subset_balanced(self):
        rows=m.pilot_bank()
        self.assertEqual(len(rows),3)
        self.assertEqual({r["label"] for r in rows},{"YES","NO","UNKNOWN"})
        self.assertEqual({r["id"].split("-")[0] for r in rows},
                         {"equal","greater","even"})
        self.assertEqual(m.manifest()["pilot"]["ids"],list(m.PILOT_IDS))

    def test_manifest_no_inference(self):
        with mock.patch.object(m,"local_infer",side_effect=AssertionError("model called")):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(m.main(["manifest"]),0)
        self.assertEqual(json.loads(out.getvalue())["pilot"]["state"],
                         "PREDECLARED_NOT_EVALUATED")

    def test_pilot_uses_exactly_three_calls(self):
        expected={r["question"]:r["label"] for r in m.pilot_bank()}
        queries=[]
        def predict(q):
            queries.append(q)
            return {"answer":expected[q],"confidence":1.0}
        outcome=m.evaluate(predict,pilot=True)
        self.assertEqual(len(queries),3)
        self.assertEqual(outcome["attempted"],3)
        self.assertEqual(outcome["graded"],3)
        self.assertEqual(outcome["state"],"PILOT_DIAGNOSTIC_ONLY")
        self.assertEqual(outcome["scoring"]["accuracy"],1.0)
        self.assertEqual(outcome["scoring"]["status"],"DESCRIPTIVE_ONLY")

    def test_one_timeout_is_not_cherrypicked(self):
        n=0
        def pred(q):
            nonlocal n
            n+=1
            if n==2:
                raise TimeoutError("never print this")
            return {"answer":"UNKNOWN","confidence":0.6}
        result=m.evaluate(pred,pilot=True)
        self.assertEqual(n,3)
        self.assertEqual(result["graded"],2)
        self.assertEqual(result["failed_or_invalid"],1)
        self.assertEqual(result["state"],"INCOMPLETE_NOT_COMPARABLE")
        self.assertNotIn("never print",json.dumps(result))

    def test_24_question_full_mode_preserved(self):
        result=m.evaluate(lambda q:{"answer":"UNKNOWN","confidence":0.5})
        self.assertEqual(result["attempted"],24)
        self.assertEqual(result["model_calls_expected"],24)
        self.assertEqual(result["state"],"COMPLETE_FIXED_BANK")

    def test_explicit_pilot_cli_as_nonroot(self):
        with mock.patch.object(m.os,"geteuid",return_value=1000), \
             mock.patch.object(m,"local_infer",return_value={"answer":"UNKNOWN","confidence":0.5}):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(m.main(["run-local-pilot"]),0)
        payload=json.loads(out.getvalue())
        self.assertEqual(payload["attempted"],3)
        self.assertEqual(payload["state"],"PILOT_DIAGNOSTIC_ONLY")

    def test_root_pilot_refused(self):
        with mock.patch.object(m.os,"geteuid",return_value=0), \
             mock.patch.object(m,"local_infer",side_effect=AssertionError("inferred")):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(m.main(["run-local-pilot"]),2)
        self.assertEqual(json.loads(out.getvalue())["state"],"ROOT_REFUSED")

    def test_invalid_flag_does_not_run(self):
        with mock.patch.object(m,"local_infer",side_effect=AssertionError("inferred")):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(m.main(["--pilot"]),2)
        self.assertEqual(json.loads(out.getvalue())["state"],"USAGE_MANIFEST_OR_RUN_LOCAL")

    def test_non_boolean_pilot_mode_rejected(self):
        with self.assertRaises(ValueError):
            m.evaluate(lambda q:{"answer":"NO","confidence":1},pilot="yes")

if __name__ == "__main__":
    unittest.main()
