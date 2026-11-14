"""Bounded Windows workload inventory; publish metadata, never file contents.

Does not start/stop tasks, read credentials into Python, open memory databases,
or modify workload files. Existing DPAPI transport posts only this inventory.
"""
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

SENSITIVE=re.compile(r'token|secret|password|credential|private|\.dpapi$|\.pem$',re.I)
MAX_FILES=20000
PS_TASKS=r"""
$ErrorActionPreference='Stop'
$rows=@(Get-ScheduledTask | Where-Object {$_.TaskName -match '^Nasuraya[A-Za-z0-9_ -]{0,70}$'} | ForEach-Object {
  $i=Get-ScheduledTaskInfo -TaskName $_.TaskName -TaskPath $_.TaskPath
  @{name=$_.TaskName;state=$_.State.ToString();last_result=$i.LastTaskResult;last_run_utc=$i.LastRunTime.ToUniversalTime().ToString('o')}
})
ConvertTo-Json -InputObject $rows -Compress
"""
PS_POST=r"""
$ErrorActionPreference='Stop'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$body=[Console]::In.ReadToEnd()
$file=Join-Path $env:ProgramData 'NasurayaBridge\github_token.dpapi'
$secure=ConvertTo-SecureString ((Get-Content -LiteralPath $file -Raw).Trim())
$ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {$key=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)}
finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)}
$h=@{Authorization=('Bearer '+$key);Accept='application/vnd.github+json';'User-Agent'='Nasuraya-Migration-Inventory'}
$uri='https://api.github.com/repos/zurvanproject/zohraya/issues/212'
$issue=Invoke-RestMethod -Method Get -Uri $uri -Headers $h -TimeoutSec 15
if ($issue.state -ne 'open' -or $issue.user.login -ne 'zurvanproject') {throw 'Issue ownership mismatch'}
$bytes=[System.Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject @{body=$body} -Compress))
$null=Invoke-RestMethod -Method Post -Uri ($uri+'/comments') -Headers $h -ContentType 'application/json' -Body $bytes -TimeoutSec 20
$key=$null;$secure=$null
'POSTED'
"""

def roots(environ):
    program=Path(environ['PROGRAMDATA'])
    local=Path(environ['LOCALAPPDATA'])
    return {
        'awake_workshop':program/'NasurayaAwake'/'workshop',
        'legacy_tadash':local/'NasurayaTadashV1',
        'model_worker':program/'NasurayaModelWorker',
        'moltbook':local/'Nasuraya'/'Moltbook',
        'public_memory':local/'Nasuraya'/'PublicMemoryV1',
        'body_atlas':program/'NasurayaBridge'/'WholeBodyAtlasV1',
        'research_96_cycles':program/'NasurayaBridge'/'nasu_24h_20261109_v1',
        'bridge_transport':program/'NasurayaBridge',
    }

def linked(path):
    info=path.lstat()
    return path.is_symlink() or bool(getattr(info,'st_file_attributes',0)&0x400)

def scan(root):
    result={'present':root.exists(),'complete':True,'files':0,'bytes':0,
            'excluded_sensitive':0,'skipped_links':0,'unreadable':0,'sqlite_files':0}
    if not result['present']:return result
    if linked(root) or not root.is_dir():
        result.update(complete=False,skipped_links=1)
        return result
    queue=[(root,0)]
    start=time.monotonic()
    while queue:
        directory,depth=queue.pop()
        if time.monotonic()-start>2 or result['files']>=MAX_FILES:
            result['complete']=False
            break
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path=Path(entry.path)
                    if SENSITIVE.search(entry.name):
                        result['excluded_sensitive']+=1
                        continue
                    if linked(path):
                        result['skipped_links']+=1
                        result['complete']=False
                    elif entry.is_dir(follow_symlinks=False):
                        if depth>=10:
                            result['complete']=False
                        elif entry.name not in ('.git','__pycache__'):
                            queue.append((path,depth+1))
                    elif entry.is_file(follow_symlinks=False):
                        result['files']+=1
                        result['bytes']+=entry.stat(follow_symlinks=False).st_size
                        result['sqlite_files']+=int(path.suffix.lower() in ('.sqlite','.sqlite3','.db'))
                    if result['files']>=MAX_FILES:
                        result['complete']=False
                        break
        except OSError:
            result['unreadable']+=1
            result['complete']=False
    return result

def powershell(script,payload=None,timeout=20):
    exe=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    result=subprocess.run([str(exe),'-NoLogo','-NoProfile','-NonInteractive','-Command',script],
                          input=payload,capture_output=True,text=True,timeout=timeout,check=False)
    if result.returncode:raise RuntimeError('PowerShell failed')
    return result.stdout.strip()

def main():
    if os.name!='nt':raise RuntimeError('Windows required')
    data={label:scan(path) for label,path in roots(os.environ).items()}
    tasks=json.loads(powershell(PS_TASKS))
    if not isinstance(tasks,list) or len(tasks)>40:raise ValueError('task shape')
    safe=[]
    for t in tasks:
        if not re.fullmatch(r'Nasuraya[A-Za-z0-9_ -]{0,70}',t['name']):raise ValueError('task name')
        if t['state'] not in ('Ready','Running','Disabled','Unknown','Queued'):raise ValueError('task state')
        safe.append({k:t[k] for k in ('name','state','last_result','last_run_utc')})
    ident=uuid.uuid4().hex
    record={'schema':'nasuraya-workload-inventory/1','id':ident,
            'observed_at':dt.datetime.now(dt.timezone.utc).isoformat(),
            'roots':data,'tasks':safe,'file_contents_read':False,'workloads_changed':False}
    body='NSINV1 ID='+ident+'\n'+json.dumps(record,sort_keys=True,separators=(',',':'))
    if len(body)>14000:raise ValueError('inventory size')
    if powershell(PS_POST,body,40)!='POSTED':raise RuntimeError('post not confirmed')
    return 'INVENTORY=POSTED;ROOTS='+str(len(data))+';FILES='+str(sum(x['files'] for x in data.values()))+';ID='+ident

if __name__=='__main__':
    try:summary=main()
    except BaseException as exc:summary='INVENTORY=BLOCKED;CAUSE='+type(exc).__name__
    print(json.dumps({'status':'ok','summary':summary},separators=(',',':')))
