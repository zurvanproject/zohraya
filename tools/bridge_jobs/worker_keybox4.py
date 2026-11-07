"""Public recipient fragment for the one-time private VPS credential transfer.
Never reads or prints an OpenAI key. RSA private XML is DPAPI-protected.
"""
import json
import os
from pathlib import Path
import subprocess

PART = 4

SCRIPT = r"""
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Security
$root=Join-Path $env:ProgramData 'NasurayaModelWorker'
$private=Join-Path $root 'recipient-private.dpapi'
$public=Join-Path $root 'recipient-public.json'
if (Test-Path (Join-Path $root 'credential-installed.json')) { throw 'Recipient already consumed' }
if (-not (Test-Path $private)) {
 if (Test-Path $public) { throw 'Incomplete existing recipient' }
 $rsa=New-Object System.Security.Cryptography.RSACryptoServiceProvider 4096
 $rsa.PersistKeyInCsp=$false
 try {
  $p=$rsa.ExportParameters($false)
  if ([Convert]::ToBase64String($p.Exponent) -ne 'AQAB') { throw 'Unexpected exponent' }
  $n=[Convert]::ToBase64String($p.Modulus).Replace('+','-').Replace('/','_').TrimEnd('=')
  $raw=[Text.Encoding]::UTF8.GetBytes($rsa.ToXmlString($true))
  try {
   $blob=[Security.Cryptography.ProtectedData]::Protect($raw,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
   [IO.File]::WriteAllBytes($private,$blob)
  } finally { [Array]::Clear($raw,0,$raw.Length) }
  $record=@{schema='nasuraya-worker-recipient/1';n=$n;e='AQAB'}
  [IO.File]::WriteAllText($public,($record|ConvertTo-Json -Compress),[Text.Encoding]::ASCII)
 } finally { $rsa.Clear() }
}
Write-Output 'RECIPIENT_READY'
"""


def root_dir():
    root=Path(os.environ["PROGRAMDATA"])/"NasurayaModelWorker"
    marker=root/"owner.json"
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise ValueError("dedicated service directory")
    if root.exists() and any(root.iterdir()) and not marker.is_file():
        raise ValueError("foreign service directory")
    root.mkdir(parents=True,exist_ok=True)
    if not marker.exists():
        marker.write_text(json.dumps({"schema":"nasuraya-model-worker/1"}),encoding="utf-8")
    elif json.loads(marker.read_text(encoding="utf-8")).get("schema")!="nasuraya-model-worker/1":
        raise ValueError("foreign owner marker")
    result=subprocess.run(["icacls.exe",str(root),"/inheritance:r","/grant:r",
                           "*S-1-5-18:(OI)(CI)F","*S-1-5-32-544:(OI)(CI)F"],
                          capture_output=True,timeout=15)
    if result.returncode:
        raise RuntimeError("private directory ACL")
    return root


if __name__=="__main__":
    try:
        root=root_dir()
        if (root/"credential-installed.json").exists():
            text="KEYBOX=CONSUMED"
        else:
            if PART==1:
                process=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",SCRIPT],
                                       capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=55)
                if process.returncode or "RECIPIENT_READY" not in process.stdout:
                    raise RuntimeError("recipient preparation")
            public=json.loads((root/"recipient-public.json").read_text(encoding="ascii"))
            n=public["n"]
            if public["e"]!="AQAB" or len(n)!=683 or not 1<=PART<=4:
                raise ValueError("recipient format")
            text="PUB"+str(PART)+"="+n[(PART-1)*171:PART*171]
        result={"status":"ok","summary":text}
    except Exception as error:
        result={"status":"ok","summary":"KEYBOX=FAILED;ERROR="+type(error).__name__}
    print(json.dumps(result,separators=(",",":")))

