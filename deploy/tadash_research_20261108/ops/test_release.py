"""Exercise the exact embedded package in an isolated directory, no network."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import py_compile
import re
import runpy
import subprocess
import sys
import tempfile
from unittest.mock import patch
import zlib

HERE=Path(__file__).resolve().parent
jobs=HERE/"jobs"
load=runpy.run_path(str(jobs/"research_evening_install.py"))
data=json.loads(zlib.decompress(base64.b85decode(load["PACK"])))
assert len((jobs/"research_evening_install.py").read_bytes())<=24000
schedule=[]
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)/"NasurayaModelWorker/research-20261108"
    root.mkdir(parents=True)
    for name,source in data.items():
        raw=source.encode()
        assert hashlib.sha256(raw).hexdigest()==load["HASHES"][name]
        (root/name).write_bytes(raw)
        py_compile.compile(str(root/name),doraise=True)
    spec=importlib.util.spec_from_file_location("runner",root/"evening_run.py")
    runner=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    config={"schema":runner.SCHEMA,"hashes":load["HASHES"],"started":0,"deadline":1199,"reference_deadline":1794159000}
    runner.atomic(root/'config.json',config)
    sample=lambda _root:dict(ok=True,native_revision=9,unresolved=0)
    system=lambda:True
    actual=runner.invoke_research
    actions=[]
    def counted(path,args):
        if "--slot" in args:actions.append(args[-1])
        return actual(path,args)
    for t,mode in [(0,"sample"),(11,"sample"),(605,"sample"),(1202,"final"),(1300,"sample")]:
        runner.run(root,mode,clock=lambda:t,system=system,sample=sample,research=counted)
    assert actions==['0','1']
    result=runner.read(root/"final.json")
    assert result['complete'] and result['health_bad']==0 and result['system'] is True
    assert result['scientific']['heldout_choices']==32768 and result['scientific']['reversal_trials']==256
    assert result['scientific']['physiology_cases']==406 and result['scientific']['control_peak_count']==0
    assert result['scientific']['reversal_gain']>0
    reports=[]
    for mode in ("science","status"):
        job=jobs/("research_evening_"+mode+".py")
        txt=subprocess.check_output([sys.executable,"-I",str(job)],env=dict(os.environ,PROGRAMDATA=tmp),text=True)
        summary=json.loads(txt)['summary']
        assert re.fullmatch(r'[a-zA-Z0-9 .,:;=/_()+-]{1,180}',summary),summary
        assert 'FINAL' in summary,summary
        reports.append(summary)
    # Inspect generated registration grammar without executing any Windows action.
    reg=load["register"]
    original=reg.__globals__["ps"]
    reg.__globals__["ps"]=lambda arg:(schedule.append(arg) or "VERIFIED")
    reg(root,config)
    reg.__globals__["ps"]=original
    assert "-Once -At $at " in schedule[0] and "New-TimeSpan -Minutes 10" in schedule[0]
    assert "NasurayaResearch20261108Final" in schedule[0]
    assert schedule[0].count("Register-ScheduledTask -TaskName")==2
    print("OK: final bundle SHA256 pins, two distinct cohort receipts, replay, calibrated trigger grammar, final and both bridge reports")
    print(*reports,sep="\n")
