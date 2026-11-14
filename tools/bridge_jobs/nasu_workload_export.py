"""Snapshot Windows workload files; upload only authenticated ciphertext.

Original files, task states, credentials, and live Awake state are unchanged.
RSA-OAEP-SHA256 wraps random encryption material and an HMAC-SHA256 key for the
existing Iran and offsite recipients. Encrypt-then-MAC covers the entire public
envelope header plus ciphertext; plaintext names/manifests remain encrypted.
"""
import base64
import datetime as dt
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import subprocess
import tempfile
import uuid
import zipfile
from xml.etree import ElementTree

PUBLIC_KEYS = {"iran":"<RSAKeyValue><Modulus>qRHj+XxjsEpJaDJZYFLl/Lk9PmwtqWpmiJzkxc2i+FZwW6qPX8g3hpZ5pg2CXRiONC2ILuG2nFmH9lRn3cxoV9kPz3wndHfDdhoAVge7UiIkHDTCApfQi8g+s99hGM95thLSYKPgWpifx2tc+dRgQgzyJXsjB00fa8DVRbMqY8oBk9VrztXOJeNFYvF/mP8kRmopJvX0GI2/NTy+c/PZrNY0GSPiWF3leWgepW/pfEIL0JXomg0tJ89OpHPI+1JUxbu2/NWPxHBgLIdhqK46VAPEk7XYRGxSPUI0yPKpgiYh1fl8NvWKpz69dvshw8e7MEI9fg9wu6xUewu5H2e7Rb0mGJKy/NTdIipH/Jyi0sks8IM5VIOH2wm5YtWOT/zOKqvs3ojMdfL/l5aIw09Uuq8ZJLM55ORMlvBY5chueQXx2U//LDej2QtUoIx4yMPrG3pajldE2xOU6tTh4TmfcsopoiY+qFrOsTajdbQYeMcLaVoQiPs0kTW2VPDH8IO/</Modulus><Exponent>AQAB</Exponent></RSAKeyValue>","offsite":"<RSAKeyValue><Modulus>n0MFljm8d4VuWQTzSvk52OXYUUPh0Qq05ki4vjan3DCpRFYVp9vrjLUv7/dAIO3HGj/1f3cl/8UpBsHyciDt5j2jTDgqGzUMTz2+0rjQrttaVeVK6gw0Pa7Q0Ppe9f7f6UQA3EM2GhSZhXwwjDU0+va8YstTcd6GlDv1kzG+++I58Ke7FQmHiExF+ULSHLf3XJItOkq7Qtc6yVgeYge5Wtjt0sq8jasi9+4MsuAHud+kKXtaBzJozR+hxz4YpWNKtx6qfBZxCaFKqiMq7uu/FUUCNt83eb5vYLor1kjWEuV9sMK8rJRqyHU1OuosS3i4ogO0kIB/G2tHLaEdnWHywMmln7Cp2IijeSQPE/+TSqLUBNxw+15FNwrMK+03vK30fntcAlIqRpeOZsyEw9caT/WpuPq9NBvgSTcLRPq/T1ygekMyl0Xmzs6mHsxTp96+r0HjiSxoLTPqO2LbRVdUZZdcidPfzuhBXI7MY+ZJa3TT7UDp440K5IJU6tkiYZaR</Modulus><Exponent>AQAB</Exponent></RSAKeyValue>"}
COMPONENTS=('awake_workshop','public_memory','body_atlas','research_96_cycles',
            'moltbook','legacy_tadash','model_worker','bridge_journal')
SENSITIVE=re.compile(r'token|secret|password|credential|private|\.dpapi$|\.pem$',re.I)
MAX_RAW=64*1024*1024
MAX_ARCHIVE=16*1024*1024
PART_CHARS=48000
BATCH=12
ISSUE='https://api.github.com/repos/zurvanproject/zohraya/issues/216'

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')
def digest(raw):return hashlib.sha256(raw).hexdigest()
def b64(raw):return base64.b64encode(raw).decode('ascii')
def mgf1(seed,length):
    return b''.join(hashlib.sha256(seed+i.to_bytes(4,'big')).digest() for i in range((length+31)//32))[:length]
def wrap_key(raw,xml):
    root=ElementTree.fromstring(xml)
    modulus=base64.b64decode(root.findtext('Modulus'),validate=True)
    exponent=int.from_bytes(base64.b64decode(root.findtext('Exponent'),validate=True),'big')
    k=len(modulus)
    if k!=384 or exponent!=65537 or len(raw)!=64:raise ValueError('recipient contract')
    db=hashlib.sha256(b'').digest()+b'\0'*(k-len(raw)-66)+b'\x01'+raw
    seed=secrets.token_bytes(32)
    masked=bytes(x^y for x,y in zip(db,mgf1(seed,k-33)))
    masked_seed=bytes(x^y for x,y in zip(seed,mgf1(masked,32)))
    return pow(int.from_bytes(b'\0'+masked_seed+masked,'big'),exponent,int.from_bytes(modulus,'big')).to_bytes(k,'big')

PS_ENCRYPT=r'''
$ErrorActionPreference='Stop'
$v=ConvertFrom-Json ([Console]::In.ReadToEnd())
$a=[System.Security.Cryptography.Aes]::Create()
try {
  $a.Key=[Convert]::FromBase64String($v.key)
  $a.IV=[Convert]::FromBase64String($v.iv)
  $a.Mode=[System.Security.Cryptography.CipherMode]::CBC
  $a.Padding=[System.Security.Cryptography.PaddingMode]::PKCS7
  $bytes=[Convert]::FromBase64String($v.data)
  $e=$a.CreateEncryptor()
  try { $cipher=$e.TransformFinalBlock($bytes,0,$bytes.Length) }
  finally { $e.Dispose() }
  [Console]::Out.Write([Convert]::ToBase64String($cipher))
} finally { $a.Dispose() }
'''

def powershell(script,payload,timeout=25,executable=None):
    exe=executable or str(Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe')
    encoded=b64(script.encode('utf-16le'))
    return subprocess.run([exe,'-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
                          input=canonical(payload),capture_output=True,timeout=timeout,check=False)

def encrypt_aes(raw,key,iv,executable=None):
    result=powershell(PS_ENCRYPT,{'key':b64(key),'iv':b64(iv),'data':b64(raw)},executable=executable)
    if result.returncode:raise RuntimeError('local encryption failed')
    cipher=base64.b64decode(result.stdout.strip(),validate=True)
    if not len(raw)<len(cipher)<=len(raw)+16 or len(cipher)%16:raise ValueError('cipher length')
    return cipher

def seal(raw,component,counts,encrypt=encrypt_aes,keys=PUBLIC_KEYS):
    if not 1<=len(raw)<=MAX_ARCHIVE:raise ValueError('archive bound')
    key=secrets.token_bytes(64);salt=secrets.token_bytes(8)
    material=hashlib.pbkdf2_hmac('sha256',b64(key[:32]).encode('ascii'),salt,100000,48)
    cipher=encrypt(raw,material[:32],material[32:])
    header={'schema':'nasuraya-workload-envelope/1','id':uuid.uuid4().hex,
            'component':component,'cipher_sha256':digest(cipher),'cipher_bytes':len(cipher),
            'archive_bytes':len(raw),'salt':b64(salt),'kdf_iterations':100000,'files':counts['files'],
            'sqlite_snapshots':counts['sqlite_snapshots'],'excluded':counts['excluded'],
            'observed_at':dt.datetime.now(dt.timezone.utc).isoformat(),
            'wrapped_keys':{role:b64(wrap_key(key,xml)) for role,xml in keys.items()}}
    tag=hmac.new(key[32:],canonical(header)+b'\n'+cipher,hashlib.sha256).hexdigest()
    return {'header':header,'tag':tag},cipher

def roots(environ):
    p=Path(environ['PROGRAMDATA']);local=Path(environ['LOCALAPPDATA'])
    return {'awake_workshop':p/'NasurayaAwake'/'workshop',
            'legacy_tadash':local/'NasurayaTadashV1','model_worker':p/'NasurayaModelWorker',
            'moltbook':local/'Nasuraya'/'Moltbook','public_memory':local/'Nasuraya'/'PublicMemoryV1',
            'body_atlas':p/'NasurayaBridge'/'WholeBodyAtlasV1',
            'research_96_cycles':p/'NasurayaBridge'/'nasu_24h_20261109_v1',
            'bridge_journal':p/'NasurayaBridge'}

def linked(path):
    info=path.lstat()
    return path.is_symlink() or bool(getattr(info,'st_file_attributes',0)&0x400)

def path_parts(name):
    parts=name.split('/')
    if not name or '\\' in name or ':' in name or any(x in ('','.','..') for x in parts):
        raise ValueError('archive path')
    return parts

def snapshot(root,component):
    if linked(root) or not root.is_dir():raise ValueError('source root')
    records=[];excluded=[];buffer=io.BytesIO();total=0;db_count=0
    queue=[root]
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        while queue:
            directory=queue.pop()
            for path in sorted(directory.iterdir()):
                name=path.relative_to(root).as_posix();parts=path_parts(name)
                if len(parts)>20:raise ValueError('source depth')
                if linked(path):raise ValueError('source link')
                if SENSITIVE.search(path.name) or path.name in ('.git','__pycache__'):
                    excluded.append({'path':name,'reason':'credential_or_cache'});continue
                if component=='bridge_journal' and name not in ('v2_journal.json','v2_health.json','bridge_v2.log'):
                    excluded.append({'path':name,'reason':'outside_transport_journal'});continue
                if path.is_dir():queue.append(path);continue
                if not path.is_file():raise ValueError('source not regular')
                if path.name.endswith(('-wal','-shm','.lock')) or 'process.lock.' in path.name:
                    excluded.append({'path':name,'reason':'sqlite_sidecar_or_process_lock'});continue
                before=path.stat()
                if before.st_size>32*1024*1024:raise ValueError('file bound')
                with path.open('rb') as stream:magic=stream.read(16)
                method='copy'
                if magic==b'SQLite format 3\0':
                    with tempfile.TemporaryDirectory(prefix='nasu-db-snapshot-') as td:
                        saved=Path(td)/'snapshot.sqlite3'
                        old=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
                        new=sqlite3.connect(saved)
                        try:
                            old.backup(new)
                            if new.execute('PRAGMA integrity_check').fetchone()!=('ok',):raise ValueError('source SQLite integrity')
                        finally:new.close();old.close()
                        raw=saved.read_bytes()
                    method='sqlite_backup';db_count+=1
                else:
                    raw=path.read_bytes();after=path.stat()
                    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('source changed during copy')
                total+=len(raw)
                if total>MAX_RAW or len(records)>=10000:raise ValueError('snapshot bound')
                archive.writestr('files/'+name,raw)
                records.append({'path':name,'bytes':len(raw),'sha256':digest(raw),'method':method})
        if not records:raise ValueError('empty source')
        manifest={'schema':'nasuraya-workload-files/1','component':component,'files':records,
                  'excluded':excluded,'total_bytes':total,'snapshot_type':'point_in_time_not_runtime_cutover'}
        archive.writestr('manifest.json',canonical(manifest))
    raw=buffer.getvalue()
    if len(raw)>MAX_ARCHIVE:raise ValueError('compressed bound')
    return raw,{'files':len(records),'sqlite_snapshots':db_count,'excluded':len(excluded)}

def messages(meta,cipher):
    h=meta['header'];prefix=' ID='+h['id']+' COMPONENT='+h['component']
    armor=b64(cipher);parts=[armor[i:i+PART_CHARS] for i in range(0,len(armor),PART_CHARS)]
    result=['NSWB1_META'+prefix+'\n'+canonical(meta).decode('ascii')]
    for i,part in enumerate(parts):result.append('NSWB1_PART'+prefix+' PART='+str(i+1)+'/'+str(len(parts))+'\n'+part)
    result.append('NSWB1_DONE'+prefix)
    return result

PS_POST=r'''
$ErrorActionPreference='Stop'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$v=ConvertFrom-Json ([Console]::In.ReadToEnd())
$file=Join-Path $env:ProgramData 'NasurayaBridge\github_token.dpapi'
$secure=ConvertTo-SecureString ((Get-Content -LiteralPath $file -Raw).Trim())
$ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {$key=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)}
finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)}
$h=@{Authorization=('Bearer '+$key);Accept='application/vnd.github+json';'User-Agent'='Nasuraya-Encrypted-Workload-Migration'}
$uri='https://api.github.com/repos/zurvanproject/zohraya/issues/216'
$issue=Invoke-RestMethod -Method Get -Uri $uri -Headers $h -TimeoutSec 10
if ($issue.state -ne 'open' -or $issue.user.login -ne 'zurvanproject') {throw 'Issue identity'}
$index=0
foreach($body in $v.messages) {
  $payload=[Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject @{body=[string]$body} -Compress))
  $null=Invoke-RestMethod -Method Post -Uri ($uri+'/comments') -Headers $h -ContentType 'application/json' -Body $payload -TimeoutSec 10
  $index++
  [Console]::Out.WriteLine('POSTED='+$index)
}
$key=$null;$secure=$null
'''

def save(path,value):
    temp=path.with_suffix('.new')
    with temp.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
    temp.replace(path)

def run():
    if os.name!='nt':raise RuntimeError('Windows required')
    home=Path(os.environ['PROGRAMDATA'])/'NasurayaWorkloadMigration'
    home.mkdir(exist_ok=True)
    if linked(home):raise ValueError('export home link')
    # Bridge already serializes jobs; keep a separate lock for manual invocations.
    lock=home/'export.lock'
    with lock.open('x') as stream:stream.write(str(os.getpid()))
    try:
        for component in COMPONENTS:
            receipt=home/(component+'.json');sealed=home/(component+'.sealed')
            if receipt.exists():
                if linked(receipt) or linked(sealed):raise ValueError('export artifact link')
                state=json.loads(receipt.read_text())
                if state.get('complete'):continue
                cipher=sealed.read_bytes();meta=state['meta']
                if digest(cipher)!=meta['header']['cipher_sha256']:raise ValueError('cached cipher changed')
            else:
                raw,counts=snapshot(roots(os.environ)[component],component)
                meta,cipher=seal(raw,component,counts)
                if sealed.exists():raise ValueError('unreviewed cipher artifact')
                with sealed.open('xb') as stream:stream.write(cipher)
                state={'meta':meta,'posted':0,'complete':False}
                save(receipt,state)
            all_messages=messages(meta,cipher);start=state['posted']
            batch=all_messages[start:start+BATCH]
            result=powershell(PS_POST,{'messages':batch},timeout=55)
            posted=[int(x) for x in re.findall(rb'(?m)^POSTED=(\d+)\r?$',result.stdout)]
            done=max(posted,default=0)
            if done>len(batch):raise ValueError('upload accounting')
            state['posted']+=done;state['complete']=state['posted']==len(all_messages)
            save(receipt,state)
            status='COMPLETE' if state['complete'] else 'PROGRESS'
            if result.returncode or done==0:status='UPLOAD_RETRY'
            return ('WORKLOAD_EXPORT='+status+';C='+component+';FILES='+str(meta['header']['files'])+
                    ';MSG='+str(state['posted'])+'/'+str(len(all_messages))+';ID='+meta['header']['id'])
        return 'WORKLOAD_EXPORT=ALL_COMPLETE;COMPONENTS=8;PLAINTEXT_PUBLISHED=0'
    finally:lock.unlink()

if __name__=='__main__':
    try:summary=run()
    except Exception as exc:
        labels={'source changed during copy':'SOURCE_BUSY','source SQLite integrity':'SQLITE_INTEGRITY',
                'file bound':'FILE_SIZE','snapshot bound':'TOTAL_SIZE','compressed bound':'ARCHIVE_SIZE',
                'source link':'SOURCE_LINK','local encryption failed':'ENCRYPTION',
                'unreviewed cipher artifact':'PARTIAL_LOCAL_ARCHIVE'}
        label=labels.get(str(exc),'UNCLASSIFIED')
        summary='WORKLOAD_EXPORT=BLOCKED;CAUSE='+type(exc).__name__+';CHECK='+label
    print(json.dumps({'status':'ok','summary':summary},separators=(',',':')))
