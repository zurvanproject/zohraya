"""One-shot Windows Awake SQLite snapshot -> dual-RSA encrypted GitHub Issue #216.
Only public RSA keys are in source; the user's GitHub credential is handled by
the existing Windows DPAPI user and PowerShell, never printed or put in GitHub.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import uuid
import zlib
from xml.etree import ElementTree
PUBLIC_KEYS = {"iran":"<RSAKeyValue><Modulus>qRHj+XxjsEpJaDJZYFLl/Lk9PmwtqWpmiJzkxc2i+FZwW6qPX8g3hpZ5pg2CXRiONC2ILuG2nFmH9lRn3cxoV9kPz3wndHfDdhoAVge7UiIkHDTCApfQi8g+s99hGM95thLSYKPgWpifx2tc+dRgQgzyJXsjB00fa8DVRbMqY8oBk9VrztXOJeNFYvF/mP8kRmopJvX0GI2/NTy+c/PZrNY0GSPiWF3leWgepW/pfEIL0JXomg0tJ89OpHPI+1JUxbu2/NWPxHBgLIdhqK46VAPEk7XYRGxSPUI0yPKpgiYh1fl8NvWKpz69dvshw8e7MEI9fg9wu6xUewu5H2e7Rb0mGJKy/NTdIipH/Jyi0sks8IM5VIOH2wm5YtWOT/zOKqvs3ojMdfL/l5aIw09Uuq8ZJLM55ORMlvBY5chueQXx2U//LDej2QtUoIx4yMPrG3pajldE2xOU6tTh4TmfcsopoiY+qFrOsTajdbQYeMcLaVoQiPs0kTW2VPDH8IO/</Modulus><Exponent>AQAB</Exponent></RSAKeyValue>","offsite":"<RSAKeyValue><Modulus>n0MFljm8d4VuWQTzSvk52OXYUUPh0Qq05ki4vjan3DCpRFYVp9vrjLUv7/dAIO3HGj/1f3cl/8UpBsHyciDt5j2jTDgqGzUMTz2+0rjQrttaVeVK6gw0Pa7Q0Ppe9f7f6UQA3EM2GhSZhXwwjDU0+va8YstTcd6GlDv1kzG+++I58Ke7FQmHiExF+ULSHLf3XJItOkq7Qtc6yVgeYge5Wtjt0sq8jasi9+4MsuAHud+kKXtaBzJozR+hxz4YpWNKtx6qfBZxCaFKqiMq7uu/FUUCNt83eb5vYLor1kjWEuV9sMK8rJRqyHU1OuosS3i4ogO0kIB/G2tHLaEdnWHywMmln7Cp2IijeSQPE/+TSqLUBNxw+15FNwrMK+03vK30fntcAlIqRpeOZsyEw9caT/WpuPq9NBvgSTcLRPq/T1ygekMyl0Xmzs6mHsxTp96+r0HjiSxoLTPqO2LbRVdUZZdcidPfzuhBXI7MY+ZJa3TT7UDp440K5IJU6tkiYZaR</Modulus><Exponent>AQAB</Exponent></RSAKeyValue>"}

ISSUE = "https://api.github.com/repos/zurvanproject/zohraya/issues/216"
POST = ISSUE + "/comments"
CHUNK = 256
BLOB_CHARS = 29000
def hash256(b):
    return hashlib.sha256(b).hexdigest()
def mgf1(seed, length):
    return b"".join(hashlib.sha256(seed+i.to_bytes(4,"big")).digest()
                    for i in range((length+31)//32))[:length]
def rsa_oaep(msg, xml):
    root = ElementTree.fromstring(xml)
    modulus = base64.b64decode(root.findtext("Modulus"),validate=True)
    exponent = int.from_bytes(base64.b64decode(root.findtext("Exponent"),validate=True),"big")
    k = len(modulus)
    if k != 384 or exponent != 65537 or len(msg)>k-66:
        raise ValueError("unexpected RSA key or message length")
    h = hashlib.sha256(b"").digest()
    db = h + b"\x00"*(k-len(msg)-66) + b"\x01" + msg
    seed = secrets.token_bytes(32)
    dbmask = mgf1(seed,k-33)
    maskeddb = bytes(a^b for a,b in zip(db,dbmask))
    seedmask = mgf1(maskeddb,32)
    maskedseed = bytes(a^b for a,b in zip(seed,seedmask))
    em = b"\x00"+maskedseed+maskeddb
    return pow(int.from_bytes(em,"big"),exponent,int.from_bytes(modulus,"big")).to_bytes(k,"big")
def snapshot():
    if os.name != "nt":
        raise RuntimeError("requires Windows")
    source = Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"))/"NasurayaAwake"/"state"/"awake.sqlite3"
    if not source.is_file() or source.is_symlink() or source.stat().st_size>16_000_000:
        raise ValueError("invalid original DB")
    with tempfile.TemporaryDirectory(prefix="nasu-migration-") as work:
        destfile=Path(work)/"awake-snapshot.sqlite3"
        old=sqlite3.connect(source.as_uri()+"?mode=ro",uri=True,timeout=8)
        new=sqlite3.connect(destfile)
        try:
            old.backup(new)
            if new.execute("PRAGMA quick_check").fetchone()[0]!="ok":
                raise ValueError("source integrity")
            schema=new.execute("SELECT value FROM control WHERE name='schema'").fetchone()
            counts=[new.execute("SELECT COUNT(*) FROM "+name).fetchone()[0]
                    for name in ("evidence","questions","ticks","ledger")]
            if schema != ("tadash-awake/1",) or not (1<=counts[0]<=2000):
                raise ValueError("source schema/count invalid")
        finally:
            new.close()
            old.close()
        raw=destfile.read_bytes()
    if len(raw)>16_000_000:
        raise ValueError("snapshot oversized")
    return raw,counts
PS = r"""
$ErrorActionPreference='Stop'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$inputData=ConvertFrom-Json ([Console]::In.ReadToEnd())
$file=Join-Path $env:ProgramData 'NasurayaBridge\github_token.dpapi'
if (-not (Test-Path -LiteralPath $file)) {throw 'Bridge credential unavailable'}
$encrypted=(Get-Content -LiteralPath $file -Raw).Trim()
$secure=ConvertTo-SecureString $encrypted
$ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {$key=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)}
finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)}
$headers=@{Authorization=('Bearer '+$key);Accept='application/vnd.github+json';'User-Agent'='Nasuraya-Encrypted-Migration';'X-GitHub-Api-Version'='2022-11-28'}
$issue=Invoke-RestMethod -Method Get -Uri 'https://api.github.com/repos/zurvanproject/zohraya/issues/216' -Headers $headers -TimeoutSec 20
if ($issue.state -ne 'open' -or $issue.user.login -ne 'zurvanproject') {throw 'Issue ownership mismatch'}
foreach($body in $inputData.comments) {
  $bodyJson=ConvertTo-Json -InputObject @{body=[string]$body} -Compress
  $bytes=[System.Text.Encoding]::UTF8.GetBytes($bodyJson)
  $null=Invoke-RestMethod -Method Post -Uri 'https://api.github.com/repos/zurvanproject/zohraya/issues/216/comments' -Headers $headers -ContentType 'application/json' -Body $bytes -TimeoutSec 20
}
$key=$null;$secure=$null
Write-Output 'UPLOAD_OK'
"""
def upload(messages):
    exe=Path(os.environ.get("SystemRoot",r"C:\Windows"))/"System32/WindowsPowerShell/v1.0/powershell.exe"
    encoded=base64.b64encode(PS.encode("utf-16le")).decode("ascii")
    result=subprocess.run([str(exe),"-NoLogo","-NoProfile","-NonInteractive","-EncodedCommand",encoded],
        input=json.dumps({"comments":messages},separators=(",",":")),text=True,
        capture_output=True,timeout=64,check=False)
    if result.returncode!=0 or "UPLOAD_OK" not in result.stdout:
        raise RuntimeError("upload rejected")
def run():
    raw,counts=snapshot()
    compressed=zlib.compress(raw,9)
    stamp=uuid.uuid4().hex
    a=[]
    for role in ("iran","offsite"):
        xml=PUBLIC_KEYS[role]
        sealed=b"".join(rsa_oaep(compressed[i:i+CHUNK],xml)
                        for i in range(0,len(compressed),CHUNK))
        armor=base64.b64encode(sealed).decode("ascii")
        parts=[armor[i:i+BLOB_CHARS] for i in range(0,len(armor),BLOB_CHARS)]
        if not 1<=len(parts)<=8:
            raise ValueError("unexpected archive size")
        header=("NSAB1 ID="+stamp+" ROLE="+role+" RAW="+hash256(raw)+
                " ZLIB="+hash256(compressed)+" ENC="+hash256(sealed)+
                " EV="+str(counts[0])+" Q="+str(counts[1])+
                " T="+str(counts[2])+" L="+str(counts[3]))
        for i,part in enumerate(parts):
            a.append(header+" PART="+str(i+1)+"/"+str(len(parts))+"\n"+part)
    a.append("NSAB1_DONE ID="+stamp+" EV="+str(counts[0])+" Q="+str(counts[1])+
             " T="+str(counts[2])+" L="+str(counts[3]))
    upload(a)
    return "EXPORT=POSTED;EV="+str(counts[0])+";Q="+str(counts[1])+";T="+str(counts[2])+";L="+str(counts[3])+";MSG="+str(len(a))+";ID="+stamp
if __name__=="__main__":
    try:
        summary=run()
    except BaseException as error:
        summary="EXPORT=BLOCKED;CAUSE="+type(error).__name__
    print(json.dumps({"status":"ok","summary":summary},separators=(",",":")))
