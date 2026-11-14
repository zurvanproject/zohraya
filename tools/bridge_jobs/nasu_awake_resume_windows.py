"""Recovery option for Windows Tadash Awake after an unsuccessful Linux cutover.
Re-enables only the two previously frozen Windows scheduled tasks.
"""
import json
import os
from pathlib import Path
import subprocess

PS = r"""
$ErrorActionPreference='Stop'
$names=@('NasurayaAwakeHourly','NasurayaAwakeIngress')
foreach($name in $names) {
  $t=Get-ScheduledTask -TaskName $name -ErrorAction Stop
  if ($null -eq $t) {throw 'task missing'}
  if ($t.State.ToString() -notin @('Disabled','Ready')) {
    Write-Output 'RESUME=BLOCKED;CAUSE=TASK_BUSY';exit 2
  }
}
foreach($name in $names) { Enable-ScheduledTask -TaskName $name -ErrorAction Stop | Out-Null }
foreach($name in $names) {
  $t=Get-ScheduledTask -TaskName $name -ErrorAction Stop
  if ($t.State.ToString() -notin @('Ready','Running')) {throw 'resume verify failed'}
}
Write-Output 'RESUME=OK;TASKS=2;WINDOWS=ACTIVE'
"""
def main():
    if os.name!="nt":return "RESUME=BLOCKED;CAUSE=NOT_WINDOWS"
    exe=Path(os.environ.get("SystemRoot",r"C:\Windows"))/"System32/WindowsPowerShell/v1.0/powershell.exe"
    p=subprocess.run([str(exe),"-NoLogo","-NoProfile","-NonInteractive","-Command",PS],
                     stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=35,check=False)
    msg=p.stdout.strip()
    valid={"RESUME=OK;TASKS=2;WINDOWS=ACTIVE","RESUME=BLOCKED;CAUSE=TASK_BUSY"}
    return msg if msg in valid else "RESUME=BLOCKED;CAUSE=UNVERIFIED"

if __name__=="__main__":
    try:output=main()
    except BaseException:output="RESUME=BLOCKED;CAUSE=UNEXPECTED"
    print(json.dumps({"status":"ok","summary":output},separators=(",",":")))
