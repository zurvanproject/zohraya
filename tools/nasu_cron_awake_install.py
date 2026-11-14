#!/usr/bin/env python3
"""Set up rootless, reboot-persistent hourly Awake cron under nasuraya.
Only modifies this account's crontab. The runner remains gated in standby
until the original Windows loop is frozen and final snapshot is imported.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

HOME=Path("/var/lib/nasuraya")
SOURCE=HOME/"zohraya"/"tools"/"nasu_awake_offline_runner.py"
BIN=HOME/"awake-bin"
INSTALLED=BIN/"awake_runner.py"
MARKER="# nasuraya-awake-offline-v1"
LINE="11 * * * * /usr/bin/python3 /var/lib/nasuraya/awake-bin/awake_runner.py >> /var/lib/nasuraya/awake-bin/hourly.log 2>&1 "+MARKER

def run(args, input_text=None):
    return subprocess.run(args, input=input_text, capture_output=True, text=True,timeout=15,check=False)

def main():
    if os.geteuid()==0 or not SOURCE.is_file():
        raise RuntimeError("wrong account or source absent")
    if shutil.which("crontab")!="/usr/bin/crontab":
        raise RuntimeError("cron command unavailable")
    for subcommand,word in (("is-active","active"),("is-enabled","enabled")):
        p=run(["/usr/bin/systemctl",subcommand,"cron.service"])
        if p.returncode!=0 or p.stdout.strip()!=word:
            raise RuntimeError("cron service is not boot-persistent")
    os.umask(0o077)
    BIN.mkdir(mode=0o700,parents=True,exist_ok=True)
    raw=SOURCE.read_bytes()
    if len(raw)>30000 or not raw.startswith(b"#!/usr/bin/env python3"):
        raise ValueError("offline runner source invalid")
    sha=hashlib.sha256(raw).hexdigest()
    existing=INSTALLED.read_bytes() if INSTALLED.exists() else None
    if existing!=raw:
        control=HOME/"awake-control.json"
        if control.is_file() and json.loads(control.read_text(encoding="utf-8")).get("enabled"):
            raise ValueError("cannot change active runner source without review")
        temp=BIN/"awake_runner.tmp"
        if temp.exists():
            raise ValueError("incomplete runner install")
        temp.write_bytes(raw)
        os.chmod(temp,0o600)
        temp.replace(INSTALLED)
    listed=run(["/usr/bin/crontab","-l"])
    if listed.returncode==0:
        old=listed.stdout
    elif listed.returncode==1 and not listed.stdout.strip() and "no crontab" in listed.stderr.lower():
        old=""
    else:
        raise RuntimeError("cannot safely read existing crontab")
    if MARKER in old:
        lines=[x for x in old.splitlines() if MARKER in x]
        if lines!=[LINE]:
            raise ValueError("existing Awake cron entry differs")
    else:
        new=old.rstrip("\n")+("\n" if old.strip() else "")+LINE+"\n"
        p=run(["/usr/bin/crontab","-"],new)
        if p.returncode:
            raise RuntimeError("cron installation failed")
    verified=run(["/usr/bin/crontab","-l"])
    if verified.returncode or verified.stdout.splitlines().count(LINE)!=1:
        raise ValueError("persisted schedule verification failed")
    print("SCHEDULE=INSTALLED;TYPE=ROOTLESS_CRON;HOURLY=11;SOURCE="+sha[:16]+
          ";GATE=STANDBY_UNTIL_CUTOVER")

if __name__=="__main__":
    try:main()
    except BaseException as exc:
        reasons={"cannot safely read existing crontab":"READ",
                 "cron installation failed":"WRITE",
                 "cron service is not boot-persistent":"DAEMON",
                 "persisted schedule verification failed":"VERIFY"}
        print("SCHEDULE=BLOCKED;CAUSE="+type(exc).__name__+
              ";DETAIL="+reasons.get(str(exc),"UNKNOWN"))
        raise SystemExit(2)
