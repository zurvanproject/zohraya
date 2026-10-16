"""Local preflight sentinel for one opt-in evidence-reuse entry point.

Not an OS/network sandbox, prompt-injection classifier, or background monitor.
Trusted manifest digest must come from the operator's separate trusted config.
"""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import sqlite3
import stat
import sys

MOTION=Path(__file__).resolve().parents[1]/'nasuraya_star_motion'
sys.path.insert(0,str(MOTION))
from time_mining import EvidenceReuse,validate_task,verify

MAX_RECEIPT_BYTES=1024*1024
MAX_MANIFEST_BYTES=128*1024
MAX_EVENTS=2048


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def bounded_bytes(path,limit):
    path=Path(path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        info=os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size>limit:raise ValueError('unsafe input file')
        data=f.read(limit+1)
        if len(data)>limit:raise ValueError('input grew beyond bound')
    return data


def bounded_json(path,limit):
    data=bounded_bytes(path,limit)
    return json.loads(data,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite JSON')))


class Sentinel:
    def __init__(self,repo_root,manifest,expected_manifest_sha256,cache,alerts):
        self.root=Path(repo_root).resolve();self.manifest=Path(manifest)
        if len(expected_manifest_sha256)!=64:raise ValueError('trusted manifest SHA256 required')
        self.expected=expected_manifest_sha256
        self.cache=Path(cache).absolute()
        if self.cache.is_symlink():raise ValueError('cache root cannot be symlink')
        self.cache.mkdir(parents=True,exist_ok=True)
        self.engine=EvidenceReuse(self.cache)
        self.alerts=Path(alerts)
        if self.alerts.is_symlink():raise ValueError('alert store cannot be symlink')
        new=not self.alerts.exists()
        self.db=sqlite3.connect(self.alerts)
        self.db.execute('PRAGMA synchronous=FULL')
        if new:
            with self.db:
                self.db.execute('CREATE TABLE control (singleton INTEGER PRIMARY KEY, latched INTEGER NOT NULL, head TEXT NOT NULL, seq INTEGER NOT NULL)')
                self.db.execute('INSERT INTO control VALUES (1,0,?,0)',('0'*64,))
                self.db.execute('CREATE TABLE events (seq INTEGER PRIMARY KEY, record TEXT NOT NULL, hash TEXT NOT NULL)')
        try:
            row=self.db.execute('SELECT latched,head,seq FROM control WHERE singleton=1').fetchone()
            if row is None:raise ValueError('missing sentinel control')
        except sqlite3.DatabaseError as exc:
            raise ValueError('foreign or corrupt alert store; never reset automatically') from exc

    def close(self):self.db.close()

    def _log_valid(self):
        head='0'*64;seq=0
        for n,encoded,h in self.db.execute('SELECT seq,record,hash FROM events ORDER BY seq'):
            seq+=1
            if n!=seq or seq>MAX_EVENTS:return False
            record=json.loads(encoded)
            if (not isinstance(record,dict) or set(record)!={'seq','previous','at_utc','code','severity'}
                or record['seq']!=seq or record['previous']!=head or h!=digest(record)):return False
            head=h
        saved=self.db.execute('SELECT head,seq FROM control WHERE singleton=1').fetchone()
        return saved==(head,seq)

    def _event(self,code,severity,latch=False):
        # Fixed event codes only; never record input text, paths, exceptions,
        # task bodies, credentials or receipt contents in security alerts.
        if code not in {'admitted','allowed','invalid_request','input_burst','source_integrity',
                        'receipt_integrity','execution_error','latched'}:
            raise ValueError('unknown internal event code')
        latched,head,seq=self.db.execute('SELECT latched,head,seq FROM control WHERE singleton=1').fetchone()
        record=dict(seq=seq+1,previous=head,at_utc=datetime.now(timezone.utc).isoformat(),
                    code=code,severity=severity)
        h=digest(record)
        with self.db:
            self.db.execute('INSERT INTO events VALUES (?,?,?)',(seq+1,json.dumps(record,sort_keys=True),h))
            self.db.execute('UPDATE control SET latched=?,head=?,seq=? WHERE singleton=1',
                            (int(bool(latched or latch)),h,seq+1))
        return dict(code=code,severity=severity,latched=bool(latched or latch))

    def _source_ok(self):
        data=bounded_bytes(self.manifest,MAX_MANIFEST_BYTES)
        if hashlib.sha256(data).hexdigest()!=self.expected:return False
        entries=json.loads(data)
        if not isinstance(entries,dict) or not 1<=len(entries)<=256:return False
        for name,expected in entries.items():
            relative=PurePosixPath(name)
            if relative.is_absolute() or '..' in relative.parts or not relative.parts:return False
            path=self.root.joinpath(*relative.parts)
            cursor=self.root
            for part in relative.parts:
                cursor=cursor/part
                if cursor.is_symlink():return False
            if hashlib.sha256(bounded_bytes(path,3*1024*1024)).hexdigest()!=expected:return False
        return True

    def execute(self,request):
        try:valid_log=self._log_valid()
        except (ValueError,TypeError,sqlite3.DatabaseError):valid_log=False
        if not valid_log:
            # Preserve the broken journal, latch separately; do not append a
            # normal event to a chain whose integrity is already unknown.
            with self.db:self.db.execute('UPDATE control SET latched=1 WHERE singleton=1')
            return dict(allowed=False,alarm=dict(code='alert_integrity',severity='critical',latched=True))
        if self.db.execute('SELECT seq FROM control WHERE singleton=1').fetchone()[0]>=MAX_EVENTS-1:
            with self.db:self.db.execute('UPDATE control SET latched=1 WHERE singleton=1')
            return dict(allowed=False,alarm=dict(code='audit_capacity',severity='high',latched=True))
        if self.db.execute('SELECT latched FROM control WHERE singleton=1').fetchone()[0]:
            return dict(allowed=False,alarm=self._event('latched','critical'))
        try:
            if not self._source_ok():raise ValueError('source')
        except (ValueError,TypeError,OSError,RecursionError):
            return dict(allowed=False,alarm=self._event('source_integrity','critical',True))
        try:
            if not isinstance(request,dict) or set(request)!={'kind','task'} or request['kind'] not in ('get','reproduce'):
                raise ValueError('request schema')
            task=validate_task(request['task'])
        except (ValueError,TypeError,KeyError):
            failures=sum(json.loads(r[0])['code']=='invalid_request' for r in self.db.execute('SELECT record FROM events'))
            burst=failures>=2
            return dict(allowed=False,alarm=self._event('input_burst' if burst else 'invalid_request',
                                                       'high' if burst else 'warning',burst))
        path=self.engine.path(task)
        try:
            if path.is_symlink() or path.exists():verify(bounded_json(path,MAX_RECEIPT_BYTES),task)
        except (ValueError,TypeError,KeyError,OSError,RecursionError):
            return dict(allowed=False,alarm=self._event('receipt_integrity','high',True))
        # Admission logging must succeed before any calculation starts.
        self._event('admitted','info')
        try:result=self.engine.execute(task,request['kind'])
        except Exception:
            return dict(allowed=False,alarm=self._event('execution_error','high',True))
        self._event('allowed','info')
        return dict(allowed=True,result=result)

    def status(self):
        valid=self._log_valid()
        latched,_,seq=self.db.execute('SELECT latched,head,seq FROM control WHERE singleton=1').fetchone()
        try:source_valid=self._source_ok()
        except (ValueError,TypeError,OSError,RecursionError):source_valid=False
        return dict(latched=bool(latched),audit_chain_valid=valid,source_valid=source_valid,events=seq,
                    monitor='on guarded request only; no background daemon',
                    visual_state='red' if latched or not valid or not source_valid else 'green')
