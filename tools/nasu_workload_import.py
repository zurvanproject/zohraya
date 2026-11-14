"""Restore authenticated, encrypted Windows archives into inactive private trees.

No executable, database trigger, model, scheduler, or social operation is run.
The active Awake database is outside this module's filesystem scope.
"""
import argparse
import base64
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import tempfile
import urllib.request
import zipfile

HOME=Path('/var/lib/nasuraya/workloads')
PRIVATE=Path('/var/lib/nasuraya/migration/recipient-private.pem')
OWNER='zurvanproject'
URL='https://api.github.com/repos/zurvanproject/zohraya/issues/216'
COMPONENTS=('awake_workshop','public_memory','body_atlas','research_96_cycles',
            'moltbook','legacy_tadash','model_worker','bridge_journal')
MAX_ARCHIVE=16*1024*1024
MAX_RAW=64*1024*1024
HEX32=re.compile(r'^[0-9a-f]{32}$')
HEX64=re.compile(r'^[0-9a-f]{64}$')
LINE=re.compile(r'^NSWB1_(META|PART|DONE) ID=([0-9a-f]{32}) COMPONENT=([a-z0-9_]+)(?: PART=([0-9]+)/([0-9]+))?$')

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')
def digest(raw):return hashlib.sha256(raw).hexdigest()
def unb64(raw):return base64.b64decode(raw,validate=True)
def path_parts(name):
    parts=name.split('/')
    if not name or '\\' in name or ':' in name or any(x in ('','.','..') for x in parts):
        raise ValueError('archive path')
    return parts

def fetch():
    def get(url):
        req=urllib.request.Request(url,headers={'User-Agent':'Nasuraya-Private-Workload-Importer','Accept':'application/vnd.github+json'})
        with urllib.request.urlopen(req,timeout=20) as response:raw=response.read(1_200_001)
        if len(raw)>1_200_000:raise ValueError('public response bound')
        return json.loads(raw)
    issue=get(URL)
    if issue.get('state')!='open' or issue.get('user',{}).get('login')!=OWNER:raise ValueError('issue identity')
    result=[]
    for page in range(1,101):
        batch=get(URL+'/comments?per_page=20&page='+str(page))
        if not isinstance(batch,list):raise ValueError('comments shape')
        result.extend(c['body'] for c in batch if c.get('user',{}).get('login')==OWNER and isinstance(c.get('body'),str))
        if len(batch)<20:return result
    raise ValueError('comment pagination incomplete')

def validate_meta(meta,component,ident):
    if set(meta)!={'header','tag'} or not HEX64.fullmatch(meta['tag']):raise ValueError('envelope shape')
    h=meta['header']
    fields={'schema','id','component','cipher_sha256','cipher_bytes','archive_bytes','salt','kdf_iterations',
            'files','sqlite_snapshots','excluded','observed_at','wrapped_keys'}
    if set(h)!=fields or h['schema']!='nasuraya-workload-envelope/1':raise ValueError('envelope schema')
    if h['component']!=component or h['id']!=ident or component not in COMPONENTS:raise ValueError('envelope identity')
    if not HEX32.fullmatch(ident) or not HEX64.fullmatch(h['cipher_sha256']):raise ValueError('envelope digest')
    if type(h['archive_bytes']) is not int or not 1<=h['archive_bytes']<=MAX_ARCHIVE:raise ValueError('archive size')
    if type(h['cipher_bytes']) is not int or not h['archive_bytes']<h['cipher_bytes']<=h['archive_bytes']+16 or h['cipher_bytes']%16:
        raise ValueError('cipher size')
    if len(unb64(h['salt']))!=8 or h['kdf_iterations']!=100000 or set(h['wrapped_keys'])!={'iran','offsite'}:raise ValueError('key envelope')
    if any(len(unb64(v))!=384 for v in h['wrapped_keys'].values()):raise ValueError('key size')
    if type(h['files']) is not int or not 1<=h['files']<=10000:raise ValueError('file count')
    for field in ('sqlite_snapshots','excluded'):
        if type(h[field]) is not int or not 0<=h[field]<=20000:raise ValueError('metadata count')
    if type(h['observed_at']) is not str or len(h['observed_at'])>50:raise ValueError('observation time')
    return h

def archives(comments):
    grouped={};done=[]
    for body in comments:
        first,sep,content=body.replace('\r\n','\n').partition('\n')
        match=LINE.fullmatch(first)
        if not match:continue
        kind,ident,component,index,total=match.groups()
        if component not in COMPONENTS:continue
        key=(component,ident);record=grouped.setdefault(key,{'meta':None,'parts':{},'total':None})
        if kind=='DONE':
            if sep and content.strip():raise ValueError('done body')
            done.append(key);continue
        if not sep:raise ValueError('missing archive body')
        if kind=='META':
            if len(content)>10000:raise ValueError('envelope bound')
            meta=json.loads(content);validate_meta(meta,component,ident)
            if record['meta'] is not None and record['meta']!=meta:raise ValueError('conflicting envelope')
            record['meta']=meta
        else:
            if index is None or total is None:raise ValueError('part identity')
            index,total=int(index),int(total)
            if not 1<=index<=total<=500 or len(content)>48000:raise ValueError('part bound')
            if record['total'] not in (None,total):raise ValueError('part count conflict')
            record['total']=total
            old=record['parts'].get(index)
            if old is not None and old!=content:raise ValueError('conflicting duplicate part')
            record['parts'][index]=content
    latest={}
    for component,ident in done:latest[component]=(component,ident)
    result={}
    for component,key in latest.items():
        r=grouped[key]
        if r['meta'] is None or r['total'] is None or set(r['parts'])!=set(range(1,r['total']+1)):
            raise ValueError('completed archive incomplete')
        cipher=unb64(''.join(r['parts'][i] for i in range(1,r['total']+1)))
        h=r['meta']['header']
        if len(cipher)!=h['cipher_bytes'] or digest(cipher)!=h['cipher_sha256']:raise ValueError('cipher digest')
        result[component]=(r['meta'],cipher)
    return result

def unwrap(meta,cipher,private=PRIVATE):
    h=validate_meta(meta,meta['header']['component'],meta['header']['id'])
    if private.is_symlink() or not private.is_file():raise ValueError('recipient key')
    result=subprocess.run(['/usr/bin/openssl','pkeyutl','-decrypt','-inkey',str(private),
        '-pkeyopt','rsa_padding_mode:oaep','-pkeyopt','rsa_oaep_md:sha256','-pkeyopt','rsa_mgf1_md:sha256'],
        input=unb64(h['wrapped_keys']['iran']),capture_output=True,timeout=10,check=False)
    if result.returncode or len(result.stdout)!=64:raise ValueError('recipient decrypt')
    key=result.stdout
    if len(cipher)!=h['cipher_bytes'] or digest(cipher)!=h['cipher_sha256']:raise ValueError('cipher digest')
    tag=hmac.new(key[32:],canonical(h)+b'\n'+cipher,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(tag,meta['tag']):raise ValueError('archive authentication')
    # OpenSSL 3 derives the AES key/IV from a random per-archive passphrase.
    # Passphrase bytes travel only over a private descriptor, never argv/env.
    with tempfile.TemporaryFile() as material:
        material.write(base64.b64encode(key[:32])+b'\n');material.seek(0)
        fd=material.fileno()
        out=subprocess.run(['/usr/bin/openssl','enc','-d','-aes-256-cbc','-pbkdf2','-iter','100000',
                            '-md','sha256','-S',unb64(h['salt']).hex(),'-pass','fd:'+str(fd)],
                           input=cipher,pass_fds=(fd,),capture_output=True,timeout=20,check=False)
    if out.returncode or len(out.stdout)!=h['archive_bytes']:raise ValueError('archive decrypt')
    return out.stdout

def manifest(archive,component,expected_files):
    entries=archive.infolist()
    if len(entries)>10001 or len({v.filename for v in entries})!=len(entries):raise ValueError('archive entries')
    info=archive.getinfo('manifest.json')
    if info.file_size>4*1024*1024:raise ValueError('manifest bound')
    record=json.loads(archive.read(info))
    if record.get('schema')!='nasuraya-workload-files/1' or record.get('component')!=component:raise ValueError('file manifest identity')
    files=record['files']
    if not isinstance(files,list) or len(files)!=expected_files or not files:raise ValueError('file manifest count')
    names={};folded=set();total=0
    for item in files:
        name=item['path'];path_parts(name)
        if name in names or name.casefold() in folded:raise ValueError('duplicate file')
        if not HEX64.fullmatch(item['sha256']) or type(item['bytes']) is not int or not 0<=item['bytes']<=32*1024*1024:raise ValueError('file record')
        if item['method'] not in ('copy','sqlite_backup'):raise ValueError('snapshot method')
        names[name]=item;folded.add(name.casefold());total+=item['bytes']
    if total>MAX_RAW or total!=record['total_bytes']:raise ValueError('raw size')
    if set(v.filename for v in entries)!={'manifest.json'}|{'files/'+name for name in names}:raise ValueError('archive file set')
    return record,names

def verify(directory,record):
    if directory.is_symlink() or directory.resolve(strict=True)!=directory:raise ValueError('import directory link')
    expected={x['path'] for x in record['files']};actual=set()
    for p in directory.rglob('*'):
        if p.is_symlink():raise ValueError('import link')
        if p.is_file():actual.add(p.relative_to(directory).as_posix())
    if actual!=expected:raise ValueError('import file set changed')
    for item in record['files']:
        p=directory.joinpath(*path_parts(item['path']))
        if p.stat().st_size!=item['bytes'] or digest(p.read_bytes())!=item['sha256']:raise ValueError('imported content changed')
        if item['method']=='sqlite_backup':
            db=sqlite3.connect(p.as_uri()+'?mode=ro&immutable=1',uri=True)
            try:
                if db.execute('PRAGMA integrity_check').fetchone()!=('ok',):raise ValueError('imported SQLite integrity')
            finally:db.close()

def unpack(raw,meta,destination):
    h=meta['header']
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        record,names=manifest(archive,h['component'],h['files'])
        if len(record['excluded'])!=h['excluded'] or sum(x['method']=='sqlite_backup' for x in names.values())!=h['sqlite_snapshots']:
            raise ValueError('snapshot counters')
        for name,item in names.items():
            info=archive.getinfo('files/'+name)
            if info.is_dir() or stat.S_IFMT(info.external_attr>>16) not in (0,stat.S_IFREG) or info.external_attr&0x10:raise ValueError('archive special file')
            if info.file_size!=item['bytes']:raise ValueError('file size')
            rawfile=archive.read(info)
            if digest(rawfile)!=item['sha256']:raise ValueError('file digest')
            p=destination.joinpath(*path_parts(name));p.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            with p.open('xb') as stream:stream.write(rawfile)
            p.chmod(0o600)
    verify(destination,record)
    return record

def save(path,value):
    temp=path.with_suffix('.new')
    with temp.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
    temp.replace(path)

def prepare(home):
    if home.resolve(strict=True)!=home:raise ValueError('workload home link')
    for name in ('imports','data-receipts'):
        p=home/name;p.mkdir(mode=0o700,exist_ok=True)
        if p.resolve(strict=True)!=p:raise ValueError('workload directory link')

def install(meta,cipher,home=HOME,private=PRIVATE):
    prepare(home);h=validate_meta(meta,meta['header']['component'],meta['header']['id'])
    component=h['component'];ident=h['id'];parent=home/'imports'/component
    parent.mkdir(mode=0o700,exist_ok=True)
    if parent.resolve(strict=True)!=parent:raise ValueError('component directory link')
    target=parent/ident
    receipt_path=home/'data-receipts'/(component+'.json')
    if receipt_path.is_symlink():raise ValueError('receipt link')
    if target.is_symlink():raise ValueError('version link')
    raw=unwrap(meta,cipher,private)
    if target.exists():
        if target.resolve(strict=True)!=target:raise ValueError('version link')
        if any((target/name).is_symlink() for name in ('manifest.json','envelope.json')):raise ValueError('metadata link')
        record=json.loads((target/'manifest.json').read_text())
        identity=json.loads((target/'envelope.json').read_text())
        if identity!=meta:raise ValueError('version conflict')
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            authenticated,_=manifest(archive,component,h['files'])
        if record!=authenticated:raise ValueError('manifest changed')
        verify(target/'files',record)
    else:
        with tempfile.TemporaryDirectory(prefix='import-',dir=parent) as td:
            stage=Path(td)/'version';stage.mkdir(mode=0o700)
            data=stage/'files';data.mkdir(mode=0o700)
            record=unpack(raw,meta,data)
            (stage/'manifest.json').write_bytes(canonical(record));(stage/'envelope.json').write_bytes(canonical(meta))
            stage.rename(target)
    report={'component':component,'id':ident,'state':'archived_verified','files':h['files'],
            'sqlite_snapshots':h['sqlite_snapshots'],'excluded':h['excluded'],
            'source_observed_at':h['observed_at'],'cipher_sha256':h['cipher_sha256'],
            'manifest_sha256':digest(canonical(record)),
            'activation':'not_started','credentials':'not_imported'}
    save(receipt_path,report)
    return report

def status(home=HOME):
    result=[]
    for component in COMPONENTS:
        entry={'component':component,'state':'missing','activation':'not_started'}
        p=home/'data-receipts'/(component+'.json')
        if p.exists():
            try:
                if p.is_symlink():raise ValueError('receipt link')
                r=json.loads(p.read_text());ident=r['id']
                if r['component']!=component or not HEX32.fullmatch(ident):raise ValueError('receipt identity')
                target=home/'imports'/component/ident
                if target.resolve(strict=True)!=target or any((target/n).is_symlink() for n in ('manifest.json','envelope.json')):
                    raise ValueError('metadata link')
                record=json.loads((target/'manifest.json').read_text());meta=json.loads((target/'envelope.json').read_text())
                h=validate_meta(meta,component,ident)
                if h['cipher_sha256']!=r['cipher_sha256'] or digest(canonical(record))!=r['manifest_sha256']:raise ValueError('receipt digest')
                verify(target/'files',record);entry.update(state='archived_verified',files=h['files'],id=ident)
            except Exception:entry['state']='invalid_requires_review'
        result.append(entry)
    return result

def main():
    if os.geteuid()==0:raise RuntimeError('service user required')
    os.umask(0o077)
    p=argparse.ArgumentParser();p.add_argument('action',choices=('import-next','import-all','status'));args=p.parse_args()
    if args.action=='status':print(json.dumps({'workload_data':status(),'credentials':'not_imported','activation':'not_started'},sort_keys=True));return
    prepare(HOME);lock=HOME/'data-import.lock'
    with lock.open('x') as stream:stream.write(str(os.getpid()))
    try:
        incoming=archives(fetch());count=0
        current={x['component']:x for x in status()}
        for component in COMPONENTS:
            if component not in incoming:continue
            if current[component]['state']=='invalid_requires_review':raise ValueError('existing archive changed')
            if current[component]['state']=='archived_verified' and current[component]['id']==incoming[component][0]['header']['id']:continue
            print(json.dumps(install(*incoming[component]),sort_keys=True),flush=True);count+=1
            if args.action=='import-next':break
        if not count:print('WORKLOAD_DATA=NO_NEW_COMPLETED_ARCHIVE;ACTIVATION=NOT_STARTED')
    finally:lock.unlink()

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('WORKLOAD_DATA=BLOCKED;CAUSE='+type(exc).__name__,flush=True)
        raise SystemExit(2)
