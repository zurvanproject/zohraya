"""Two real-clock awakenings in separate CLI processes; generated body, no API."""
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
import time

from .api_host import BodyAPIHost
from .care import episodes
from .continuation import authorize
from .host import BodyLoop
from .scheduler import register, utcnow

ROOT = Path(__file__).resolve().parents[2]


def demo(output_dir):
    output = Path(output_dir)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    path = output/'session.sqlite'
    with BodyLoop.start(path,fixture='sleep',max_actions=1) as loop:
        old=BodyAPIHost(loop,mode='bounded',target_cycles=1,max_calls=8,run_id='care-old')
        def invoke(name,label,args=None):
            return old.handle_required('care-seed',dict(type='function_call',name=name,arguments=args or {},
                call_id=label,turn_id='care-seed-turn'))
        observation=json.loads(invoke('observe_body','observe')['output'])
        invoke('evaluate_body','evaluate')
        seeded=invoke('request_body_action','action',dict(action='walk',duration_s=.1,
            observed_checkpoint_sha256=observation['checkpoint_sha256']))
        invoke('evaluate_body','finish')
        assert seeded['success'] and old.evaluate()['goal_reached']
        before=old.snapshot()
        seed=json.loads(seeded['output'])
        # Fixture-only explicit setup grant. Care and scheduler never authorize.
        grant=authorize(loop,grant_id='care-grant',run_id='care-goal',additional_actions=2,additional_calls=8,
                        observed_checkpoint_sha256=before['checkpoint_sha256'])
        due=utcnow()+timedelta(seconds=2)
        schedule=register(loop,wake_id='care-wake',run_id='care-goal',model='deterministic-fixture',backend='care',
            due_at=due.isoformat(),expires_at=(due+timedelta(minutes=2)).isoformat(),retry_delay_seconds=1)
    checks=[]
    for _ in range(15):
        checked=utcnow()
        proc=subprocess.Popen([sys.executable,'-m','examples.nasuraya_body_loop','wake',
            '--session',str(path),'--wake-id','care-wake'],cwd=ROOT,text=True,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            stdout,stderr=proc.communicate(timeout=30)
        except BaseException:
            proc.kill();proc.communicate();raise
        if proc.returncode:
            raise RuntimeError('care demo CLI did not complete successfully')
        row=json.loads(stdout)
        checks.append(dict(at_utc=checked.isoformat(),dispatcher_pid=proc.pid,
            state=row['state'],attempts=row['attempts'],status=row['last_status'],
            execution_started=row['execution_started']))
        if row['state']=='completed':
            break
        time.sleep(1)
    with BodyLoop(path) as loop:
        host=BodyAPIHost.resume(loop,run_id='care-goal')
        memories=episodes(loop,'care-goal')
        evaluation=host.evaluate()
        after=host.snapshot()
        history_before=loop.engine.export()
    replay=subprocess.run([sys.executable,'-m','examples.nasuraya_body_loop','wake',
        '--session',str(path),'--wake-id','care-wake'],cwd=ROOT,capture_output=True,text=True,timeout=30)
    assert replay.returncode==0
    assert not json.loads(replay.stdout)['execution_started']
    with BodyLoop(path) as loop:
        assert history_before==loop.engine.export()
        assert memories==episodes(loop,'care-goal')
    assert len(memories)==2 and evaluation['goal_reached']
    assert evaluation['run_actions_remaining']==evaluation['tool_calls_remaining']==0
    assert seed['decision_id'] in memories[0]['recalled_feedback_ids']
    assert memories[0]['decision_id'] in memories[1]['recalled_feedback_ids']
    summary=dict(schema='nasuraya-care-continuity-demo/1',status='completed',
        generated_fixture=True,real_host_clock_polling=True,separate_cli_processes=True,
        live_model_execution=False,api_network_requests=0,permanent_service_installed=False,
        seed_body_action=seed['actual_action'],seed_requested_action=seed['requested_action'],
        initial_revision=before['revision'],final_revision=after['revision'],grant=grant,
        schedule=schedule['contract'],checks=checks,evaluation=evaluation,episodes=memories,
        terminal_replay_execution_started=False,history_preserved_on_terminal_replay=True)
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,sort_keys=True))
    return 0
