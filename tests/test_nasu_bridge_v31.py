"""Offline contracts for the non-deployed GitHub Bridge v3 candidate."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]

def load(file,name):
    s=importlib.util.spec_from_file_location(name,ROOT/"tools"/file)
    m=importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m

r=load("nasu_bridge_research.py","research")
p=load("preview_nasuraya_bridge_v31.py","patcher")

FIXTURE = '''import re
import subprocess
COMMAND_RE = re.compile(r"(?m)^\\s*nasu-linux:\\s*(status|agent-status|agent-probe|help)\\s*$", re.I)
def command(argv, timeout=30, cwd=None):
    return (argv,timeout,cwd)
def dispatch(action):
    if action == "status":
        return "old status"
    if action == "agent-status":
        return "agent status"
    if action == "agent-probe":
        return "agent probe"
    return "Allowed: status, agent-status, agent-probe, help. No arbitrary shell."
def poll():
    body = "nasu-linux: status"
    match = COMMAND_RE.search(body)
    return match
if api("GET", "/user").get("login") != OWNER:
    pass
# subprocess.run(argv helper is unchanged
'''

class BridgeContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"research"

    def test_whitelist_and_bound(self):
        self.assertEqual(r.TASK_ISSUE,290)
        self.assertEqual(len(r.work_items()),16)
        self.assertEqual({i[1] for i in r.work_items()}, {"M0P0","M1P0","M0P1","M1P1"})
        self.assertLessEqual(r.MAX_CALLS,16)
        self.assertLessEqual(r.MAX_WALL_S,1800)

    def test_principles_and_memory_are_isolated_by_arm(self):
        case=r.CASES[0]
        a=r.prompt_for(case,"M0P0",False,False)
        b=r.prompt_for(case,"M1P0",True,False)
        c=r.prompt_for(case,"M0P1",False,True)
        d=r.prompt_for(case,"M1P1",True,True)
        self.assertNotIn(case["memory"],a)
        self.assertIn(case["memory"],b)
        self.assertIn(r.PRINCIPLES,c)
        self.assertNotIn(r.PRINCIPLES,b)
        self.assertIn(case["memory"],d)
        self.assertNotIn('"gold"',d)

    def test_no_write_when_status_missing(self):
        x=r.minimal_status(self.root)
        self.assertEqual(x["state"],"not_started")
        self.assertFalse(self.root.exists())

    def test_start_idempotence_and_no_real_process_spawn(self):
        fake=lambda *args,**kwargs: type("Child",(),{"pid":9876})()
        one=r.start(self.root,spawn=fake)
        self.assertEqual(one["state"],"started")
        self.assertEqual(r.start(self.root,spawn=fake)["state"],"not_started_refused")
        self.assertEqual(r.state(self.root)["state"],"pending")

    def test_full_workflow_fake_model_and_local_receipts(self):
        r.start(self.root,spawn=lambda *a,**k:type("Child",(),{"pid":123})())
        out=r.work(self.root,model=lambda prompt:{"choice":"TEST","reason":"synthetic","cost":"unknown","critique":"possible","revision":"new test"})
        self.assertEqual(out["state"],"completed")
        self.assertEqual(out["completed"],16)
        self.assertEqual(out["valid"],16)
        self.assertEqual(out["correct"],4)
        self.assertEqual(out["errors"],0)
        self.assertEqual(len((self.root/"results.jsonl").read_text().splitlines()),16)
        self.assertEqual(r.work(self.root)["state"],"not_pending")
        self.assertNotIn("synthetic",r.canonical(r.minimal_status(self.root)))

    def test_bad_model_rows_do_not_become_success(self):
        r.start(self.root,spawn=lambda *a,**k:type("Child",(),{"pid":1})())
        out=r.work(self.root,model=lambda prompt:{"choice":"invalid"})
        self.assertEqual(out["completed"],16)
        self.assertEqual(out["valid"],0)
        self.assertEqual(out["errors"],16)
        self.assertEqual(out["state"],"finished_with_errors")

    def test_stop_is_cooperative_and_no_trust_leap(self):
        r.start(self.root,spawn=lambda *a,**k:type("Child",(),{"pid":1})())
        self.assertEqual(r.stop(self.root)["state"],"stop_requested")
        x=r.work(self.root,model=lambda prompt: (_ for _ in ()).throw(AssertionError("ran")))
        self.assertEqual(x["state"],"stopped")
        self.assertEqual(x["completed"],0)

    def test_model_exact_schema_and_local_request(self):
        ans={"choice":"A","reason":"test","cost":"unknown","critique":"alternative","revision":"new evidence"}
        data=json.dumps({"done":True,"model":r.MODEL,"response":json.dumps(ans)}).encode()
        seen=[]
        def opener(req,*,timeout):
            seen.append((req.full_url,timeout,json.loads(req.data)))
            return io.BytesIO(data)
        self.assertEqual(r.infer("test",open_request=opener),ans)
        self.assertEqual(seen[0][0],r.URL)
        self.assertEqual(seen[0][1],r.PER_CALL_TIMEOUT_S)
        self.assertEqual(seen[0][2]["model"],r.MODEL)
        self.assertTrue(seen[0][2]["think"] is False)

    def test_truncated_json_rejected(self):
        data=json.dumps({"done":True,"model":r.MODEL,"response":'{"choice":"A","reason":"unfinished'}).encode()
        with self.assertRaises(json.JSONDecodeError):
            r.infer("test",open_request=lambda *a,**k:io.BytesIO(data))

    def test_wrong_model_refused(self):
        data=json.dumps({"done":True,"model":"other","response":"{}"}).encode()
        with self.assertRaisesRegex(ValueError,"unverified_model"):
            r.infer("test",open_request=lambda *a,**k:io.BytesIO(data))

    def test_invalid_root_refused(self):
        with self.assertRaises(ValueError):
            r.guard_root(Path("relative"))
        link=Path(self.tmp.name)/"symlink"
        link.symlink_to(self.root)
        with self.assertRaises(ValueError):
            r.guard_root(link)

    def test_patch_adds_only_fixed_verbs_handlers_and_strict_match(self):
        output=p.patch(FIXTURE)
        self.assertIn("COMMAND_RE.fullmatch(body.split(", output)
        self.assertIn("research-start",output)
        self.assertIn("nasu_bridge_research.py",output)
        ns={"api":lambda *a:{"login":"owner"},"OWNER":"owner"}
        exec(output,ns)
        self.assertEqual(ns["dispatch"]("status"),"old status")
        self.assertEqual(ns["dispatch"]("agent-probe"),"agent probe")
        self.assertTrue(ns["COMMAND_RE"].fullmatch("nasu-linux: research-start"))
        self.assertFalse(ns["COMMAND_RE"].fullmatch("note\nnasu-linux: research-start"))
        self.assertFalse(ns["COMMAND_RE"].fullmatch("nasu-linux: research-start && echo hack"))
        ns["poll"] = ns["poll"]  # existence check for legacy first-line routing
        command,limit,cwd=ns["dispatch"]("research-start")
        self.assertEqual(command[-2:], ["/usr/local/lib/nasuraya/nasu_bridge_research.py","start"])
        self.assertEqual(limit,30)

    def test_patch_rejects_double_extension_and_drift(self):
        with self.assertRaises(ValueError):
            p.patch(p.patch(FIXTURE))
        with self.assertRaises(ValueError):
            p.patch(FIXTURE.replace("COMMAND_RE.search(body)","COMMAND_RE.match(body)"))
        with self.assertRaises(ValueError):
            p.patch(FIXTURE.replace("agent-status|agent-probe", "agent-status"))

    def test_patch_changes_no_existing_command_argv(self):
        out=p.patch(FIXTURE)
        self.assertIn('if action == "agent-status":\n        return "agent status"',out)
        self.assertIn('if action == "status":\n        return "old status"',out)

    def test_simulated_21_verb_installed_shape_roundtrips_all_old_handlers(self):
        verbs=list(sorted(p.EXISTING_ACTIONS - {"help"}))+["help"]
        branches="".join(f'    if action == "{v}":\n        return "pre-existing:{v}"\n' for v in verbs[:-1])
        src=("import re\nimport subprocess\n"
             "COMMAND_RE = re.compile(r\"(?m)^\\s*nasu-linux:\\s*("+"|".join(verbs)+")\\s*$\", re.I)\n"
             "def command(argv, timeout=30, cwd=None):\n    return argv,timeout,cwd\n"
             "def dispatch(action):\n" + branches + "    return 'Allowed: original commands'\n"
             "def poll():\n    body='nasu-linux: status'\n    match = COMMAND_RE.search(body)\n    return match\n"
             "if api(\"GET\", \"/user\").get(\"login\") != OWNER:\n    pass\n"
             "# subprocess.run(argv helper is unchanged\n")
        updated=p.patch(src)
        a={"api":lambda *args:{"login":"owner"},"OWNER":"owner"}
        exec(updated,a)
        for name in verbs[:-1]:
            self.assertEqual(a["dispatch"](name), "pre-existing:"+name)
        self.assertEqual(len(set(verbs)),21)
        self.assertTrue(a["COMMAND_RE"].fullmatch("nasu-linux: research-start"))
        self.assertIsNone(a["COMMAND_RE"].fullmatch("nasu-linux: arbitrary-run"))

    def test_live_allowlist_guard_rejects_wrong_hash(self):
        self.assertEqual(len(p.EXISTING_ACTIONS),21)
        self.assertEqual(len(p.PINNED_INSTALLED_SHA256),64)
        with self.assertRaisesRegex(ValueError,"installed_sha256_changed_refuse"):
            p.patch(FIXTURE, exact_live=True)

    def test_atomic_write_survives_stale_tmp_file(self):
        self.root.mkdir(parents=True)
        (self.root/"status.json.tmp").write_text("leftover from crash")
        r._atomic(self.root/"status.json",{"ok":True})
        self.assertTrue(json.loads((self.root/"status.json").read_text())["ok"])

    def test_first_line_match_preserves_explanations_but_refuses_embedded(self):
        output=p.patch(FIXTURE)
        test=output.replace('body = "nasu-linux: status"',
                            'body = "nasu-linux: research-start\\n\\nOwner explanation"')
        ns={"api":lambda *a:{"login":"owner"},"OWNER":"owner"}
        exec(test,ns)
        self.assertEqual(ns["poll"]().group(1),"research-start")
        test=output.replace('body = "nasu-linux: status"',
                            'body = "Description\\nnasu-linux: research-start"')
        ns={"api":lambda *a:{"login":"owner"},"OWNER":"owner"}
        exec(test,ns)
        self.assertIsNone(ns["poll"]())

if __name__=="__main__":
    unittest.main()
