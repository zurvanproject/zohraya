"""One-shot reversible freeze of the TWO Windows Tadash Awake tasks only.
Bridge V2 remains active and original SQLite contents remain untouched.
"""
import json
import os
from pathlib import Path
import subprocess

PS = r"""
$ErrorActionPreference='Stop'
$names=@('NasurayaAwakeHourly','NasurayaAwakeIngress')
$old=@{}
foreach($name in $names) {
  $task=Get-ScheduledTask -TaskName $name -ErrorAction Stop
  if ($null -eq $task) {throw 'missing task'}
  $status=$task.State.ToString()
  if ($status -notin @('Ready','Disabled')) {Write-Output 'FREEZE=BLOCKED;CAUSE=TASK_BUSY';exit 2}
  $old[$name]=$status
}
try {
  foreach($name in $names) {
    if ($old[$name] -eq 'Ready') {Disable-ScheduledTask -TaskName $name -ErrorAction Stop | Out-Null}
  }
  foreach($name in $names) {
    if ((Get-ScheduledTask -TaskName $name).State.ToString() -ne 'Disabled') {
      throw 'freeze verification failed'
    }
  }
  Write-Output 'FREEZE=OK;TASKS=2;HOURLY=DISABLED;INGRESS=DISABLED;BRIDGE=UNCHANGED'
} catch {
  foreach($name in $names) {
    if ($old[$name] -eq 'Ready') {
      try {Enable-ScheduledTask -TaskName $name -ErrorAction Stop | Out-Null} catch {}
    }
  }
  Write-Output 'FREEZE=BLOCKED;CAUSE=ROLLED_BACK'
  exit 3
}
"""
def main():
    if os.name!="nt":
        return "FREEZE=BLOCKED;CAUSE=NOT_WINDOWS"
    exe=Path(os.environ.get("SystemRoot",r"C:\Windows"))/"System32/WindowsPowerShell/v1.0/powershell.exe"
    p=subprocess.run([str(exe),"-NoLogo","-NoProfile","-NonInteractive","-Command",PS],
                     stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=35,check=False)
    safe={"FREEZE=OK;TASKS=2;HOURLY=DISABLED;INGRESS=DISABLED;BRIDGE=UNCHANGED",
          "FREEZE=BLOCKED;CAUSE=TASK_BUSY","FREEZE=BLOCKED;CAUSE=ROLLED_BACK"}
    msg=p.stdout.strip()
    return msg if msg in safe else "FREEZE=BLOCKED;CAUSE=UNVERIFIED"

if __name__=="__main__":
    try:output=main()
    except BaseException:output="FREEZE=BLOCKED;CAUSE=UNEXPECTED"
    print(json.dumps({"status":"ok","summary":output},separators=(",",":")))
