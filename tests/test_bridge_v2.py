"""Offline regression checks for Nasuraya Bridge v2."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import bridge_v2 as b


class BridgeV2Tests(unittest.TestCase):
    def test_rejects_shell_and_non_pinned_commands(self):
        self.assertIsNone(b.parse_job("nasu: powershell dir"))
        self.assertIsNone(b.parse_job("nasu: run abc other 123"))
        self.assertIsNone(b.parse_job("nasu: run " + "a"*40 + " ../evil " + "b"*64))

    def test_accepts_only_full_pins(self):
        self.assertEqual(b.parse_job("nasu: run " + "a"*40 + " runtime_probe " + "b"*64),
                         ("a"*40, "runtime_probe", "b"*64))

    def test_no_secret_in_public_result(self):
        self.assertEqual(b.safe_summary(json.dumps({"status":"ok","summary":"PASS=True"}),0),"OK PASS=True")
        self.assertEqual(b.safe_summary(json.dumps({"status":"ok","summary":"password=abc"}),0),"INVALID_JOB_RESULT")

    def test_remote_result_deduplication(self):
        comments=[
            {"id":100,"user":{"login":b.OWNER},"body":"nasu: run "+"a"*40+" runtime_probe "+"b"*64},
            {"id":101,"user":{"login":b.OWNER},"body":"Nasuraya Bridge v2 result; request_id=comment-100; command=run runtime_probe"},
        ]
        def mock_api(token,path,method="GET",data=None):
            if path.endswith("/issues/149"):
                return {"state":"open","user":{"login":b.OWNER}}
            raise AssertionError("unexpected network operation")
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(b,"api_request",side_effect=mock_api):
                with mock.patch.object(b,"get_comments",return_value=comments):
                    with mock.patch.object(b,"execute_job",side_effect=AssertionError("duplicate attempted")):
                        self.assertEqual(b.poll("dummy",Path(folder)),(2,0))

    def test_lost_reply_does_not_duplicate_execution(self):
        comments=[{"id":200,"user":{"login":b.OWNER},"body":"nasu: run "+"a"*40+" runtime_probe "+"b"*64}]
        counter={"job":0,"post":0}
        def api(token,path,method="GET",data=None):
            if method=="POST":
                counter["post"]+=1
                if counter["post"]==1:
                    raise b.URLError("temporary")
                return {}
            return {"state":"open","user":{"login":b.OWNER}}
        def execute(*args):
            counter["job"]+=1
            return "OK PASS=True"
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(b,"api_request",side_effect=api):
                with mock.patch.object(b,"get_comments",return_value=comments):
                    with mock.patch.object(b,"execute_job",side_effect=execute):
                        with self.assertRaises(b.URLError):
                            b.poll("dummy",Path(folder))
                        self.assertEqual(b.poll("dummy",Path(folder)),(1,1))
                        self.assertEqual(counter["job"],1)


if __name__=="__main__":
    unittest.main()
