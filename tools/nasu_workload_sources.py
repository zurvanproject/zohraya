#!/usr/bin/env python3
"""Stage immutable public workload sources. Never execute or activate them.

Windows-local state, credentials, model calls, social actions and the live Awake
database are outside this module. A source archive is not a runtime migration.
"""
import argparse
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import urllib.request
import zipfile

HOME=Path('/var/lib/nasuraya/workloads')
CATALOG=Path('/usr/local/lib/nasuraya/workload_catalog.json')
REPO='zurvanproject/zohraya'
MAX_ZIP=32*1024*1024
MAX_RAW=40*1024*1024

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args):return None

def get(url,limit):
    allowed=(f'https://api.github.com/repos/{REPO}/git/trees/',
             f'https://codeload.github.com/{REPO}/zip/')
    if not url.startswith(allowed):raise ValueError('URL outside fixed repository')
    req=urllib.request.Request(url,headers={'User-Agent':'Nasuraya-Workload-Source-Migration','Accept':'application/vnd.github+json'})
    with urllib.request.build_opener(NoRedirect()).open(req,timeout=45) as response:
        data=response.read(limit+1)
    if not data or len(data)>limit:raise ValueError('response bound')
    return data

def catalog(path=CATALOG):
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema')!='nasuraya-workload-sources/1' or data.get('repository')!=REPO:
        raise ValueError('catalog schema')
    items=data['components']
    if not 1<=len(items)<=16:raise ValueError('component bound')
    seen=set()
    for item in items:
        if not re.fullmatch('[a-z][a-z0-9_]{0,40}',item['id']) or item['id'] in seen:
            raise ValueError('component id')
        seen.add(item['id'])
        if any(not re.fullmatch('[a-f0-9]{40}',item[k]) for k in ('commit','tree')):
            raise ValueError('source identity')
        if not 1<=item['blob_count']<=2000 or not 1<=item['total_bytes']<=MAX_RAW:
            raise ValueError('source bound')
    return items

def relative(name):
    p=PurePosixPath(name)
    if (not name or p.is_absolute() or '\\' in name or ':' in name or
        any(x in ('','.','..') for x in name.split('/'))):
        raise ValueError('unsafe archive path')
    return p

def blob_sha(raw):
    return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

def expected_files(component,tree):
    if tree.get('truncated') is not False or tree.get('sha')!=component['tree']:
        raise ValueError('tree identity or completeness')
    files={}
    for entry in tree['tree']:
        if entry['type']=='tree':continue
        if entry['type']!='blob' or entry['mode'] not in ('100644','100755'):
            raise ValueError('nonregular Git entry')
        relative(entry['path'])
        if entry['path'] in files or not re.fullmatch('[a-f0-9]{40}',entry['sha']):
            raise ValueError('duplicate or invalid blob')
        if not 0<=entry['size']<=8*1024*1024:raise ValueError('file bound')
        files[entry['path']]={'sha':entry['sha'],'size':entry['size'],'mode':entry['mode']}
    if len(files)!=component['blob_count'] or sum(x['size'] for x in files.values())!=component['total_bytes']:
        raise ValueError('source counts differ')
    return files

def unpack(raw,component,files,destination):
    if len(raw)>MAX_ZIP:raise ValueError('zip bound')
    prefix='zohraya-'+component['commit']+'/'
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries=archive.infolist()
        if len(entries)>5000:raise ValueError('archive entries')
        seen=set()
        total=0
        for entry in entries:
            if not entry.filename.startswith(prefix):raise ValueError('archive prefix')
            name=entry.filename[len(prefix):]
            if entry.is_dir():
                if name:relative(name.rstrip('/'))
                continue
            relative(name)
            if name not in files or name in seen:raise ValueError('unexpected or duplicate file')
            # Some codeload archives omit Unix mode metadata entirely. The Git
            # tree is authoritative: only 100644/100755 blobs reach this point,
            # and we create plain files ourselves after verifying their hashes.
            # Still reject explicit symlink/device types and the DOS dir flag.
            file_type=stat.S_IFMT(entry.external_attr>>16)
            if file_type not in (0,stat.S_IFREG) or entry.external_attr&0x10:
                raise ValueError('archive symlink or special file')
            if entry.file_size!=files[name]['size']:raise ValueError('file size differs')
            total+=entry.file_size
            if total>MAX_RAW:raise ValueError('unpacked bound')
            body=archive.read(entry)
            if blob_sha(body)!=files[name]['sha']:raise ValueError('Git blob mismatch')
            target=destination.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as handle:handle.write(body)
            os.chmod(target,0o700 if files[name]['mode']=='100755' else 0o600)
            seen.add(name)
        if seen!=set(files):raise ValueError('missing archive files')

def verify(directory,files):
    if directory.is_symlink() or directory.resolve(strict=True)!=directory:
        raise ValueError('untrusted source directory')
    actual=set()
    for path in directory.rglob('*'):
        if path.is_symlink():raise ValueError('source symlink')
        if path.is_file():actual.add(path.relative_to(directory).as_posix())
    if actual!=set(files):raise ValueError('source file set changed')
    for name,record in files.items():
        p=directory.joinpath(*PurePosixPath(name).parts)
        if p.stat().st_size!=record['size'] or blob_sha(p.read_bytes())!=record['sha']:
            raise ValueError('staged source changed')

def atomic_json(path,value):
    temp=path.with_suffix('.new')
    with temp.open('x',encoding='utf-8') as handle:
        json.dump(value,handle,sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)

def prepare(home):
    if home.resolve(strict=True)!=home:raise ValueError('workload home symlink')
    for folder in ('sources','receipts','manifests'):
        path=home/folder
        path.mkdir(mode=0o700,exist_ok=True)
        if path.resolve(strict=True)!=path:raise ValueError('workload folder symlink')

def stage(component,home=HOME,fetch=get):
    prepare(home)
    ident=component['id']
    target=home/'sources'/ident
    manifest=home/'manifests'/(ident+'.json')
    receipt=home/'receipts'/(ident+'.json')
    if any(path.is_symlink() for path in (target,manifest,receipt)):
        raise ValueError('workload metadata symlink')
    if receipt.exists():
        record=json.loads(receipt.read_text())
        if record.get('commit')!=component['commit'] or record.get('tree')!=component['tree']:
            raise ValueError('staged version conflict')
        files=expected_files(component,json.loads(manifest.read_text()))
        verify(target,files)
        return {'component':ident,'source':'verified_existing','execution':'not_started'}
    tree=json.loads(fetch(f'https://api.github.com/repos/{REPO}/git/trees/{component["tree"]}?recursive=1',1_000_000))
    files=expected_files(component,tree)
    if target.exists():
        verify(target,files)
    else:
        raw=fetch(f'https://codeload.github.com/{REPO}/zip/{component["commit"]}',MAX_ZIP)
        with tempfile.TemporaryDirectory(prefix='source-stage-',dir=home) as td:
            directory=Path(td)/'source'
            directory.mkdir()
            unpack(raw,component,files,directory)
            verify(directory,files)
            directory.rename(target)
    if manifest.exists():
        if expected_files(component,json.loads(manifest.read_text()))!=files:raise ValueError('manifest conflict')
    else:atomic_json(manifest,tree)
    record={'schema':'nasuraya-staged-source/1','component':ident,
            'commit':component['commit'],'tree':component['tree'],
            'verified_files':len(files),'verified_bytes':component['total_bytes'],
            'observed_at':dt.datetime.now(dt.timezone.utc).isoformat(),
            'private_state':'not_imported','execution':'not_started'}
    atomic_json(receipt,record)
    return record

def status(items,home=HOME):
    output=[]
    for item in items:
        result={'component':item['id'],'source':'missing','execution':'not_started',
                'next':item['readiness']}
        receipt=home/'receipts'/(item['id']+'.json')
        if receipt.is_file():
            try:
                if receipt.is_symlink() or (home/'manifests'/(item['id']+'.json')).is_symlink():
                    raise ValueError('workload metadata symlink')
                record=json.loads(receipt.read_text())
                if record.get('commit')!=item['commit'] or record.get('tree')!=item['tree']:
                    raise ValueError('receipt identity')
                files=expected_files(item,json.loads((home/'manifests'/(item['id']+'.json')).read_text()))
                verify(home/'sources'/item['id'],files)
                result['source']='verified'
            except Exception:result['source']='invalid_requires_review'
        output.append(result)
    return output

def main():
    if os.geteuid()==0:raise RuntimeError('requires service account')
    os.umask(0o077)
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('stage-next','stage-all','status'))
    args=parser.parse_args()
    items=catalog()
    if args.action=='status':
        print(json.dumps({'workloads':status(items),'private_state':'not_imported','autostart':False},sort_keys=True))
        return
    prepare(HOME)
    lock=HOME/'staging.lock'
    with lock.open('x') as handle:handle.write(str(os.getpid()))
    try:
        for component in items:
            result=stage(component)
            print(json.dumps(result,sort_keys=True),flush=True)
            if args.action=='stage-next' and result.get('source')!='verified_existing':break
    finally:lock.unlink()

def failure_summary(exc):
    # Only fixed public validation labels may leave this process. Unexpected
    # network/OS messages can contain paths or URLs and are never published.
    labels={
        'archive symlink or special file':'ARCHIVE_FILE_TYPE',
        'archive prefix':'ARCHIVE_PREFIX',
        'unsafe archive path':'ARCHIVE_PATH',
        'Git blob mismatch':'BLOB_HASH',
        'tree identity or completeness':'TREE_IDENTITY',
        'source counts differ':'TREE_COUNTS',
        'file size differs':'FILE_SIZE',
        'unexpected or duplicate file':'ARCHIVE_FILE_SET',
        'missing archive files':'ARCHIVE_INCOMPLETE',
        'staged source changed':'EXISTING_SOURCE_CHANGED',
        'source file set changed':'EXISTING_FILE_SET_CHANGED',
    }
    code=labels.get(str(exc),'UNCLASSIFIED') if isinstance(exc,ValueError) else 'UNCLASSIFIED'
    return 'WORKLOAD_SOURCES=BLOCKED;CAUSE='+type(exc).__name__+';CHECK='+code

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(failure_summary(exc),flush=True)
        raise SystemExit(2)
