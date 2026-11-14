"""Read only retained workshop counters; never expose private state content."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3

def unseal(raw):
    seal=json.loads(raw)
    encoded=json.dumps(seal['value'],sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    if hashlib.sha256(encoded).hexdigest()!=seal['sha256']:raise ValueError('integrity')
    return seal['value']

def run():
    path=Path(os.environ['PROGRAMDATA'])/'NasurayaAwake'/'workshop'/'session.sqlite'
    if not path.is_file() or path.is_symlink():raise ValueError('workshop missing')
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
    try:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        config=unseal(db.execute('SELECT value FROM config').fetchone()[0])
        head=unseal(db.execute('SELECT value FROM head').fetchone()[0])
        if config['schema']!='nasuraya.shared-session/3' or config['session_id']!='awakevps' or config['backend']!='workshop':raise ValueError('lineage')
        state=head['state'];workshop=state['workshop']
        values=[state['revision'],state['actions_used'],config['max_actions'],workshop['pending_jobs'],workshop['completed_jobs'],workshop['energy'],workshop['heat']]
        if any(type(v) is not int or not 0<=v<=10000 for v in values):raise ValueError('counters')
        safe=workshop['energy']>=15 and workshop['heat']<=85
        complete=workshop['pending_jobs']==0 and safe
        return ('WORKSHOP=SIM;REV='+str(values[0])+';ACTIONS='+str(values[1])+'/'+str(values[2])+
                ';PENDING='+str(values[3])+';COMPLETED='+str(values[4])+
                ';GOAL='+('COMPLETE' if complete else 'PENDING')+';SOURCE_WRITES=0;MODEL_CALLS=0')
    finally:db.close()

if __name__=='__main__':
    try:summary=run()
    except Exception as exc:summary='WORKSHOP_READINESS=BLOCKED;CAUSE='+type(exc).__name__
    print(json.dumps({'status':'ok','summary':summary},separators=(',',':')))
