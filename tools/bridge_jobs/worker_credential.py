"""One-use encrypted credential delivery; no plaintext credentials in this job."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess

CIPHERTEXT="bvNKq9MKvSphh5VgwKZiCXhjmDwh0ZK6kKr0U2AFUqwUMC61I2OOqzqWozBif2kvmxSdKOZsW0SmVVQIbc3yjFQJLfZEhKJpLWGhoRE496YvcywvFEQDNTfQYXDSQ0IcpsWLnHLUKSiViFGmeq+9f1io9iwJ3eOzd5g7idkwfoalEHQOw27hS+XlGlDcgkUTJEHxdtWsOoLdBvcSAkSomHiwNTFZ5qacnnaIfWrEZgRSII4uAJFN2d4LewgcjuFzwSqNLrWcLZoYCKK2J/aKmgB9PHmOYJME7lnQPG8IIDi5YDHfhAK/QjwljR9JnwGYmXnfVFHZJ4UquLA19VukwysPSSA3VEVvzNzNlszt2f5VUt95xe8JjlZYy7eHyNCYK47leJDgqe4GBfYp4TJsTccVVJjlDyVO3NASbL4NIjzJxYWo2lv3nQI07kjgnW41mT3JSjnXY2Rl0u99p95jQgjEwSWlVw1c5qajclymkGyWLO+59pQZ3IzE3nVRFQ6aI2bw1O7pryFzy2MYbO+AtydfC1h9WCKGZSDNKjlo1ly5YU6ImuHWnWCwOh/EMTgRm64ss15odlZ1sjZsbcw9gmv+5+qTjGLZoxgu6JnHVZ7z2BFuQ0DesnkKzO7fC3dgpXeHee64SELOHZoGHp/arIHNLhTJiaw/hP/rLv74akc="
ENVELOPE_SHA256="56b94c57adc271bbe6ba981b10d4b6e207c67c55d7afe68e7d30c525b65bb182"
SCRIPT=r"""
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Security
$root=Join-Path $env:ProgramData 'NasurayaModelWorker'
$target=Join-Path $root 'api-key.dpapi'
$marker=Join-Path $root 'credential-installed.json'
$envelope='56b94c57adc271bbe6ba981b10d4b6e207c67c55d7afe68e7d30c525b65bb182'
if (Test-Path $marker) {
 $old=Get-Content -Raw $marker | ConvertFrom-Json
 if (($old.envelope_sha256 -ne $envelope) -or (-not (Test-Path $target))) { throw 'Credential conflict' }
 Write-Output 'CREDENTIAL_INSTALLED'
 exit 0
}
if (Test-Path $target) { throw 'Unmarked credential' }
$private=Join-Path $root 'recipient-private.dpapi'
$raw=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($private),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
$rsa=New-Object System.Security.Cryptography.RSACryptoServiceProvider
$rsa.PersistKeyInCsp=$false
try {
 $rsa.FromXmlString([Text.Encoding]::UTF8.GetString($raw))
 $plain=$rsa.Decrypt([Convert]::FromBase64String('bvNKq9MKvSphh5VgwKZiCXhjmDwh0ZK6kKr0U2AFUqwUMC61I2OOqzqWozBif2kvmxSdKOZsW0SmVVQIbc3yjFQJLfZEhKJpLWGhoRE496YvcywvFEQDNTfQYXDSQ0IcpsWLnHLUKSiViFGmeq+9f1io9iwJ3eOzd5g7idkwfoalEHQOw27hS+XlGlDcgkUTJEHxdtWsOoLdBvcSAkSomHiwNTFZ5qacnnaIfWrEZgRSII4uAJFN2d4LewgcjuFzwSqNLrWcLZoYCKK2J/aKmgB9PHmOYJME7lnQPG8IIDi5YDHfhAK/QjwljR9JnwGYmXnfVFHZJ4UquLA19VukwysPSSA3VEVvzNzNlszt2f5VUt95xe8JjlZYy7eHyNCYK47leJDgqe4GBfYp4TJsTccVVJjlDyVO3NASbL4NIjzJxYWo2lv3nQI07kjgnW41mT3JSjnXY2Rl0u99p95jQgjEwSWlVw1c5qajclymkGyWLO+59pQZ3IzE3nVRFQ6aI2bw1O7pryFzy2MYbO+AtydfC1h9WCKGZSDNKjlo1ly5YU6ImuHWnWCwOh/EMTgRm64ss15odlZ1sjZsbcw9gmv+5+qTjGLZoxgu6JnHVZ7z2BFuQ0DesnkKzO7fC3dgpXeHee64SELOHZoGHp/arIHNLhTJiaw/hP/rLv74akc='),$true)
 try {
  $entropy=[Text.Encoding]::UTF8.GetBytes('NasurayaModelWorker/api-key/v1')
  $protected=[Security.Cryptography.ProtectedData]::Protect($plain,$entropy,[Security.Cryptography.DataProtectionScope]::LocalMachine)
  $check=[Security.Cryptography.ProtectedData]::Unprotect($protected,$entropy,[Security.Cryptography.DataProtectionScope]::LocalMachine)
  try {
   if ([Convert]::ToBase64String($check) -ne [Convert]::ToBase64String($plain)) { throw 'DPAPI check failed' }
   [IO.File]::WriteAllBytes(($target+'.tmp'),$protected)
   Move-Item -LiteralPath ($target+'.tmp') -Destination $target
   $record=@{schema='nasuraya-worker-credential/1';envelope_sha256=$envelope;scope='LocalMachine'}
   [IO.File]::WriteAllText($marker,($record|ConvertTo-Json -Compress),[Text.Encoding]::ASCII)
  } finally { [Array]::Clear($check,0,$check.Length) }
 } finally { [Array]::Clear($plain,0,$plain.Length) }
} finally { [Array]::Clear($raw,0,$raw.Length);$rsa.Clear() }
Remove-Item -LiteralPath $private -Force
Remove-Item -LiteralPath (Join-Path $root 'recipient-public.json') -Force
Write-Output 'CREDENTIAL_INSTALLED'
"""

def main():
 root=Path(os.environ["PROGRAMDATA"])/"NasurayaModelWorker"
 if json.loads((root/"owner.json").read_text())!={"schema":"nasuraya-model-worker/1"}:raise ValueError("dedicated owner")
 if hashlib.sha256(base64.b64decode(CIPHERTEXT,validate=True)).hexdigest()!=ENVELOPE_SHA256:raise ValueError("envelope fingerprint")
 result=subprocess.run(["icacls.exe",str(root),"/inheritance:r","/grant:r","*S-1-5-18:(OI)(CI)F","*S-1-5-32-544:(OI)(CI)F"],capture_output=True,timeout=15)
 if result.returncode:raise ValueError("private ACL")
 result=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",SCRIPT],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=45)
 if result.returncode or "CREDENTIAL_INSTALLED" not in result.stdout:raise RuntimeError("credential delivery failed")
 return "CREDENTIAL=INSTALLED;SCOPE=MACHINE;ACL=PRIVATE"

if __name__=="__main__":
 try:summary=main()
 except Exception as error:summary="CREDENTIAL=FAILED;ERROR="+type(error).__name__
 print(json.dumps({"status":"ok","summary":summary},separators=(",",":")))
