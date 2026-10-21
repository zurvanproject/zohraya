"""Render existing systemd templates for a real Linux host; no installation/grants."""
import argparse
import hashlib
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent


def prepare(output,*,repo,session,wake_id,user):
    for value in (repo,session):
        if not Path(value).is_absolute() or not re.fullmatch(r'/[A-Za-z0-9_./-]+',value):
            raise ValueError('absolute literal host paths required')
        if '..' in Path(value).parts:raise ValueError('normalized host path required')
    if not re.fullmatch('[A-Za-z0-9_-]{1,80}',wake_id):raise ValueError('fixed wake ID required')
    if not re.fullmatch('[a-z_][a-z0-9_-]{0,31}',user):raise ValueError('literal Linux service user required')
    out=Path(output);out.mkdir(mode=0o700,parents=True,exist_ok=False)
    service=(HERE/'nasuraya-wake.service.example').read_text()
    service=service.replace('/opt/zohraya',repo).replace('/var/lib/nasuraya/session.sqlite',session)
    service=service.replace('User=nasuraya','User='+user).replace('--wake-id approved-wake','--wake-id '+wake_id)
    service=service.replace('ReadWritePaths=/var/lib/nasuraya','ReadWritePaths='+str(Path(session).parent))
    # Runtime key file is already approved and private at the repo; no secret in units.
    service=service.replace('EnvironmentFile=/etc/nasuraya/runtime.env\n','')
    service=service.replace('# Template only; not installed. Replace paths, account and fixed wake ID.\n',
        '# Prepared host unit; not installed by this helper.\n')
    timer=(HERE/'nasuraya-wake.timer.example').read_text()
    (out/'nasuraya-wake.service').write_text(service)
    (out/'nasuraya-wake.timer').write_text(timer)
    manifest=dict(schema='nasuraya-prepared-host/1',repo=repo,session=session,wake_id=wake_id,user=user,
        installed=False,creates_grants=False,can_refill_budget=False,
        prerequisites=['real persistent Linux host with systemd','repo source and pinned SDK',
                       'owned persistent SQLite path','approved private .env.local at repo'],
        file_sha256={name:hashlib.sha256((out/name).read_bytes()).hexdigest()
                     for name in ('nasuraya-wake.service','nasuraya-wake.timer')})
    (out/'host-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir',required=True);p.add_argument('--repo',required=True)
    p.add_argument('--session',required=True);p.add_argument('--wake-id',required=True)
    p.add_argument('--user',default='nasuraya');a=p.parse_args()
    print(json.dumps(prepare(a.output_dir,repo=a.repo,session=a.session,wake_id=a.wake_id,user=a.user)))
