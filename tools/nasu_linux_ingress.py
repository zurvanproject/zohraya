#!/usr/bin/env python3
"""Continue the original simulated Windows workshop on Ubuntu without reset.

Uses the already verified source snapshots and an independent working copy of
the authenticated workshop archive. The active Awake DB remains authoritative.
No model, network, credential, physical-device or social action is performed.
"""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import uuid

sys.dont_write_bytecode=True
BASE=Path('/var/lib/nasuraya')
HOME=BASE/'workloads'
LIVE=HOME/'ingress-live'
BACKUPS=HOME/'ingress-backups'
CATALOG=Path('/usr/local/lib/nasuraya/workload_catalog.json')
SOURCE_PINS={'runtime_78kg':'d86750d8d26d4ea6a3fe595f9e1ee81e95d81fec',
             'awake_ingress':'320ce8adcc789f11f8966ca2c7251fd860fa44f6'}

def helper(installed,local):
    path=Path(__file__).with_name(installed)
    if not path.is_file():path=Path(__file__).with_name(local)
    spec=importlib.util.spec_from_file_location('ingress_'+local.replace('.','_'),path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode('ascii')
def sha(raw):return hashlib.sha256(raw).hexdigest()

def regular(path):
    if not path.is_file() or path.is_symlink() or path.resolve(strict=True)!=path:
        raise ValueError('regular path required')
    return path

def atomic(path,value):
    if path.is_symlink():raise ValueError('receipt link')
    fd,name=tempfile.mkstemp(prefix='receipt-',dir=path.parent);tmp=Path(name)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(value,f,sort_keys=True);f.flush();os.fsync(f.fileno())
        tmp.replace(path)
    finally:
        if tmp.exists():tmp.unlink()

def current_state():
    receipt=json.loads(regular(BASE/'migration'/'latest-import.json').read_text())
    gate=json.loads(regular(BASE/'awake-control.json').read_text())
    if (gate.get('schema')!='nasuraya-awake-offline/1' or gate.get('enabled') is not True
            or gate.get('import_id')!=receipt.get('id')):
        raise ValueError('active Awake gate required')
    db=Path(receipt['working_db'])
    if db.parent.parent!=BASE/'migration'/'working':raise ValueError('Awake version path')
    regular(db)
    conn=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=5)
    try:
        conn.execute('PRAGMA query_only=ON')
        if conn.execute("SELECT value FROM control WHERE name='schema'").fetchone()!=('tadash-awake/1',):raise ValueError('Awake schema')
        if conn.execute("SELECT value FROM control WHERE name='paused'").fetchone()!=('0',):raise ValueError('Awake paused')
    finally:conn.close()
    return db.parent,receipt['id']

def verified_sources():
    source_helper=helper('workload_sources.py','nasu_workload_sources.py')
    items={x['id']:x for x in source_helper.catalog(CATALOG)};paths={}
    for ident,pin in SOURCE_PINS.items():
        item=items[ident]
        if item['commit']!=pin:raise ValueError('source pin changed')
        manifest=json.loads(regular(HOME/'manifests'/(ident+'.json')).read_text())
        files=source_helper.expected_files(item,manifest)
        path=HOME/'sources'/ident;source_helper.verify(path,files);paths[ident]=path
    return paths

def archived_workshop():
    importer=helper('workload_import.py','nasu_workload_import.py')
    path=regular(HOME/'data-receipts'/'awake_workshop.json')
    receipt=json.loads(path.read_text())
    if receipt.get('component')!='awake_workshop' or receipt.get('state')!='archived_verified' or not importer.HEX32.fullmatch(receipt['id']):
        raise ValueError('verified workshop archive required')
    version=HOME/'imports'/'awake_workshop'/receipt['id']
    record=json.loads(regular(version/'manifest.json').read_text())
    if sha(importer.canonical(record))!=receipt['manifest_sha256']:raise ValueError('workshop archive manifest')
    if record['component']!='awake_workshop' or record['excluded']:raise ValueError('complete workshop required')
    importer.verify(version/'files',record)
    regular(version/'files'/'session.sqlite')
    return version/'files',receipt,record

def modules(paths):
    sys.path.insert(0,str(paths['awake_ingress']))
    sys.path.insert(0,str(paths['runtime_78kg']))
    from tadash_awake import live_ingress
    from examples.nasuraya_runtime.session import Session
    if Path(live_ingress.__file__).resolve()!=paths['awake_ingress']/'tadash_awake'/'live_ingress.py':
        raise ValueError('ingress module origin')
    if Path(sys.modules[Session.__module__].__file__).resolve()!=paths['runtime_78kg']/'examples'/'nasuraya_runtime'/'session.py':
        raise ValueError('session module origin')
    # Adapt only the installation path and process-lock hook. All simulation,
    # stream identity, recovery, hourly pacing and 48-action rules stay pinned.
    live_ingress.checked_source=lambda _:paths['runtime_78kg']
    return live_ingress,Session

def snapshot(Session):
    regular(LIVE/'workshop'/'session.sqlite')
    with Session(LIVE/'workshop') as session:snap=session.snapshot()
    if snap['session_id']!='awakevps' or snap['backend']!='workshop' or snap['body_profile']!='tadash_reduced_78kg_v1':
        raise ValueError('workshop lineage')
    if snap['stopped'] or snap['revision']!=snap['actions_used'] or not 1<=snap['revision']<=48:
        raise ValueError('workshop state or budget')
    if snap['actions_used']+snap['actions_remaining']!=48:raise ValueError('original action budget changed')
    return snap

def goal_state(snap):
    from examples.nasuraya_agent_loop.local import State,evaluate
    return evaluate(State(**snap['workshop']))

def prepare():
    if HOME.resolve(strict=True)!=HOME:raise ValueError('workload home link')
    state,awake_id=current_state();paths=verified_sources()
    source,receipt,record=archived_workshop()
    if LIVE.exists():
        origin=json.loads(regular(LIVE/'origin.json').read_text())
        if origin['archive_id']!=receipt['id'] or origin['awake_import_id']!=awake_id or origin['pins']!=SOURCE_PINS:
            raise ValueError('existing live lineage differs')
        if not (LIVE/'state').is_symlink() or (LIVE/'state').resolve(strict=True)!=state:raise ValueError('existing state link differs')
    else:
        with tempfile.TemporaryDirectory(prefix='ingress-prepare-',dir=HOME) as td:
            stage=Path(td)/'ready';stage.mkdir(mode=0o700)
            shutil.copytree(source,stage/'workshop',symlinks=False)
            (stage/'state').symlink_to(state,target_is_directory=True)
            origin={'schema':'nasuraya-linux-ingress/1','archive_id':receipt['id'],
                    'manifest_sha256':receipt['manifest_sha256'],'awake_import_id':awake_id,'pins':SOURCE_PINS}
            (stage/'origin.json').write_bytes(canonical(origin))
            stage.rename(LIVE)
    if LIVE.resolve(strict=True)!=LIVE:raise ValueError('live root link')
    live,Session=modules(paths);snap=snapshot(Session)
    # Exact six existing revision IDs must be present before this migrated
    # workshop is first advanced; a new/empty session is never manufactured.
    age=live.last_imported(LIVE,snap,live.core.clock())
    if age is None:raise ValueError('archive revision not in authoritative Awake')
    BACKUPS.mkdir(mode=0o700,exist_ok=True)
    if BACKUPS.resolve(strict=True)!=BACKUPS:raise ValueError('backup path link')
    return {'status':'prepared','revision':snap['revision'],'actions_remaining':snap['actions_remaining'],
            'goal':goal_state(snap),'source':'SIM','network_calls':0,'model_calls':0,'awake_replaced':False}

def preflight():
    state,awake_id=current_state()
    origin=json.loads(regular(LIVE/'origin.json').read_text())
    if origin.get('schema')!='nasuraya-linux-ingress/1' or origin['awake_import_id']!=awake_id or origin['pins']!=SOURCE_PINS:
        raise ValueError('live lineage mismatch')
    if LIVE.resolve(strict=True)!=LIVE or not (LIVE/'state').is_symlink() or (LIVE/'state').resolve(strict=True)!=state:
        raise ValueError('authoritative state link mismatch')
    paths=verified_sources();live,Session=modules(paths)
    return live,Session,state

def backup_pair(state,phase):
    BACKUPS.mkdir(mode=0o700,exist_ok=True)
    if BACKUPS.resolve(strict=True)!=BACKUPS:raise ValueError('backup path link')
    ident=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]+'-'+phase
    folder=BACKUPS/ident;folder.mkdir(mode=0o700)
    hashes={}
    for name,path in (('awake',state/'awake.sqlite3'),('workshop',LIVE/'workshop'/'session.sqlite')):
        target=folder/(name+'.sqlite3')
        source=sqlite3.connect(regular(path).as_uri()+'?mode=ro',uri=True,timeout=10)
        dest=sqlite3.connect(target)
        try:
            source.backup(dest)
            if dest.execute('PRAGMA integrity_check').fetchone()!=('ok',):raise ValueError('backup integrity')
            if dest.execute('PRAGMA journal_mode=DELETE').fetchone()[0].lower()!='delete':raise ValueError('backup journal')
        finally:dest.close();source.close()
        target.chmod(0o600);hashes[name]=sha(target.read_bytes())
    (folder/'hashes.json').write_bytes(canonical(hashes))
    return ident

class NoopInnerLock:
    def unlink(self):pass

def run(now=None):
    live,Session,state=preflight()
    lock_path=LIVE/'process-lease.sqlite3'
    if lock_path.is_symlink():raise ValueError('lease link')
    lease=sqlite3.connect(lock_path,timeout=0,isolation_level=None);lease.execute('BEGIN EXCLUSIVE')
    try:
        before=snapshot(Session);at=live.core.clock(now)
        age=live.last_imported(LIVE,before,at)
        complete=goal_state(before)['goal_reached']
        pending=(age is None or (not complete and before['revision']<48 and age>=live.MIN_INGRESS_SECONDS))
        backup_before=backup_pair(state,'before') if pending else None
        live.exclusive_lock=lambda _:NoopInnerLock()
        if complete and age is not None:
            counts=live.core.status(state)['counts']
            result={'status':'completed_awaiting_new_goal','imported':0,
                    'awake_events':counts['evidence'],'awake_questions':counts['questions']}
        else:result=live.run(LIVE,now=at)
        after=snapshot(Session)
        if after['revision']-before['revision'] not in (0,1) or result.get('imported',0) not in (0,6):raise ValueError('unexpected continuation')
        backup_after=backup_pair(state,'after') if pending else None
        safe={'status':result['status'],'observed_at':at.isoformat(),'before_revision':before['revision'],'revision':after['revision'],
              'actions_remaining':after['actions_remaining'],'imported':result.get('imported',0),
              'events':result.get('awake_events'),'questions':result.get('awake_questions'),
              'goal':goal_state(after),
              'source':'SIM','network_calls':0,'model_calls':0,'external_actions':0,
              'backup_before':backup_before,'backup_after':backup_after}
        atomic(LIVE/'last-linux.json',safe)
        return safe
    finally:lease.close()

def status():
    live,Session,state=preflight();snap=snapshot(Session)
    result={'status':'ready','revision':snap['revision'],'actions_remaining':snap['actions_remaining'],
            'goal':goal_state(snap),'source':'SIM','network_calls':0,'model_calls':0}
    if (LIVE/'last-linux.json').exists():
        result['last']=json.loads(regular(LIVE/'last-linux.json').read_text())
    return result

def main():
    if os.geteuid()==0:raise RuntimeError('service user required')
    os.umask(0o077)
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('prepare','run','status'));args=parser.parse_args()
    value={'prepare':prepare,'run':run,'status':status}[args.action]()
    print(json.dumps(value,sort_keys=True))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        labels={'archive revision not in authoritative Awake':'HISTORY_MISMATCH',
                'workshop lineage':'WORKSHOP_LINEAGE','session implementation changed; explicit migration required':'SOURCE_IDENTITY',
                'existing live lineage differs':'EXISTING_LINEAGE','Awake paused':'AWAKE_PAUSED',
                'active Awake gate required':'GATE','source pin changed':'SOURCE_PIN'}
        print('INGRESS=BLOCKED;CAUSE='+type(exc).__name__+';CHECK='+labels.get(str(exc),'LOCAL_REVIEW'))
        raise SystemExit(2)
