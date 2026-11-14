#!/usr/bin/env python3
"""Read-only discovery for an unattended unprivileged Linux scheduler."""
import json
import os
import shutil
import subprocess

def probe():
    available=shutil.which("crontab") is not None
    result={"cron_tool":bool(available),"cron_active":False,"cron_enabled":False,
            "user_crontab_readable":False,"user":"nasuraya"}
    if os.geteuid()==0:
        return {"status":"wrong_account"}
    def check(args):
        try:
            p=subprocess.run(args,capture_output=True,text=True,timeout=5,check=False)
            return p.returncode,p.stdout.strip()
        except (OSError,subprocess.TimeoutExpired):
            return -1,""
    for field,command,success in (
        ("cron_active",["/usr/bin/systemctl","is-active","cron.service"],"active"),
        ("cron_enabled",["/usr/bin/systemctl","is-enabled","cron.service"],"enabled")):
        rc,out=check(command)
        result[field]=(rc==0 and out==success)
    if available:
        rc,out=check(["/usr/bin/crontab","-l"])
        result["user_crontab_readable"]=rc in (0,1)
    result["unprivileged_schedule_possible"]=all(
        (result["cron_tool"],result["cron_active"],result["cron_enabled"],
         result["user_crontab_readable"]))
    return result

if __name__=="__main__":
    print("SCHEDULE_PROBE "+json.dumps(probe(),sort_keys=True,separators=(",",":")))
