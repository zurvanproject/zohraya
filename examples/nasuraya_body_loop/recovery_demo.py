"""Reproduce bounded local recovery and cold restart without a model/API call.

Run with the verified native runtime on PYTHONPATH. The optional source session
is copied with SQLite backup, never reset or modified. Its continuation grant is
three one-second actions and twelve body-tool calls, with no automatic refill.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from .host import BodyLoop
from .api_host import BodyAPIHost
from .continuation import authorize
from .recovery import recovery_status, recovery_step
from synthetic_fixture import prepare_defaults

RUN_ID = 'bounded-recovery-20261014'


def saved_goals(loop):
    return dict(loop.engine.db.execute('SELECT id,contract FROM body_api_runs'))


def reopen(path, replay=False):
    with BodyLoop(path) as loop:
        host = BodyAPIHost.resume(loop, run_id=RUN_ID)
        before = host.snapshot()
        rows = []
        if replay:
            result = recovery_step(host)
            assert not result['executed']
            assert before == host.snapshot()
        else:
            for _ in range(host.target_cycles):
                if host.evaluate()['goal_reached']:
                    break
                result = recovery_step(host)
                rows.append(result)
                if not result['executed']:
                    break
        return dict(snapshot=host.snapshot(), evaluation=host.evaluate(),
                    recovery=recovery_status(host), events=rows,
                    network_requests=0, model_calls=0,
                    actions_this_process=loop.status()['actions_reserved']-host.opening_reserved)


def run(output, source=None):
    output = Path(output)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    path = output / 'session.sqlite'
    prepare_defaults()
    source_hash = None
    if source:
        source = Path(source)
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        # Read-only source, including committed WAL; destination is exclusively new.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        with sqlite3.connect(source.resolve().as_uri()+'?mode=ro', uri=True) as src:
            with sqlite3.connect(path) as dst:
                src.backup(dst)
        loop = BodyLoop(path)
        old_records = deepcopy(loop.records())
        old_goals = saved_goals(loop)
        old_config = deepcopy(loop.config)
        before = loop.status()['self_model']
        max_calls = int(loop.engine.db.execute("SELECT value FROM meta WHERE key='body-api-call-limit'").fetchone()[0])
        authorize(loop, grant_id='bounded-recovery-grant-20261014', run_id=RUN_ID,
                  additional_actions=3, additional_calls=12,
                  observed_checkpoint_sha256=before['checkpoint_sha256'])
        target = 3
    else:
        loop = BodyLoop.start(path, fixture='recovery-ready', max_actions=2)
        old_records, old_goals, old_config = [], {}, deepcopy(loop.config)
        before = loop.status()['self_model']
        max_calls, target = 12, 2
    with loop:
        host = BodyAPIHost(loop, mode='bounded', target_cycles=target,
                           max_calls=max_calls, run_id=RUN_ID)
        first = recovery_step(host)
        assert first['receipt']['actual_action']=='sleep'
        assert first['recovery']['sleep_pressure'] < before['minimum_state']['sleep_pressure']
    command = [sys.executable, '-m', 'examples.nasuraya_body_loop.recovery_demo', '--resume', str(path)]
    child = subprocess.run(command, capture_output=True, text=True, check=True)
    resumed = json.loads(child.stdout)
    replay = subprocess.run(command+['--replay'], capture_output=True, text=True, check=True)
    reread = json.loads(replay.stdout)
    assert reread['snapshot']==resumed['snapshot']
    assert reread['actions_this_process']==0
    assert resumed['evaluation']['goal_reached']
    with BodyLoop(path) as loop:
        assert loop.records()[:len(old_records)]==old_records
        assert all(saved_goals(loop).get(k)==v for k,v in old_goals.items())
        assert loop.config==old_config
        assert loop.status()['actions_remaining']==0
    if source:
        assert hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
        assert not resumed['recovery']['completed'], 'three seconds are not full recovery from .95'
    else:
        assert resumed['recovery']['actions']==['sleep','walk']
        assert resumed['recovery']['completed']
    summary = dict(scope='local controller, actual native software-body execution; zero model calls',
        case='continued_saved_fixture' if source else 'declared_near_threshold_fixture',
        before=before['minimum_state'], after=resumed['snapshot']['minimum_state'],
        recovery=resumed['recovery'], evaluation=resumed['evaluation'],
        preserved_prior_decisions=len(old_records), preserved_prior_goals=len(old_goals),
        original_body_config_preserved=True, source_file_unchanged=bool(source),
        first_action=first, resumed=resumed,
        cold_replay_actions=reread['actions_this_process'], model_calls=0,
        final_checkpoint=resumed['snapshot']['checkpoint_sha256'])
    (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    (output/'replay.json').write_text(json.dumps(reread, ensure_ascii=False, indent=2)+'\n')
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', type=Path)
    p.add_argument('--source-session', type=Path)
    p.add_argument('--resume', type=Path)
    p.add_argument('--replay', action='store_true')
    a=p.parse_args()
    if a.resume:
        result=reopen(a.resume, a.replay)
    else:
        if not a.output_dir: p.error('--output-dir required')
        result=run(a.output_dir, a.source_session)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
