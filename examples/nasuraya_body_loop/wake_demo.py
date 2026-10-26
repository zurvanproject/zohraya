"""Real host-clock polling of one explicitly granted generated-fixture mission."""
from datetime import timedelta
import json
from pathlib import Path
import time

from .api_host import BodyAPIHost
from .continuation import authorize
from .host import BodyLoop
from .scheduler import register, synthetic_runner, tick, utcnow


def demo(output_dir):
    output = Path(output_dir)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    path = output / 'session.sqlite'
    with BodyLoop.start(path, fixture='sleep', max_actions=1) as loop:
        old = BodyAPIHost(loop, mode='bounded', target_cycles=1, max_calls=4, run_id='demo-old')
        synthetic_runner(old, {}, 30)
        before = old.snapshot()
        # Only this disposable fixture setup issues the explicit demo grant.
        # The scheduler module has no authorization operation.
        grant = authorize(loop, grant_id='demo-grant', run_id='demo-wake',
            additional_actions=1, additional_calls=4,
            observed_checkpoint_sha256=before['checkpoint_sha256'])
        due = utcnow() + timedelta(seconds=2)
        schedule = register(loop, wake_id='demo-wake', run_id='demo-wake', model='synthetic-fixture',
            due_at=due.isoformat(), expires_at=(due+timedelta(minutes=2)).isoformat(), backend='synthetic')
    rows = []
    for _ in range(30):
        at = utcnow()
        row = tick(path, wake_id='demo-wake')
        rows.append(dict(checked_at_utc=at.isoformat(), state=row['state'], attempts=row['attempts'],
                         execution_started=row['execution_started']))
        if row['state'] != 'pending':
            break
        time.sleep(1)
    with BodyLoop(path) as loop:
        host = BodyAPIHost.resume(loop, run_id='demo-wake')
        after = host.snapshot()
        evaluation = host.evaluate()
        counters_before_replay = loop.status()['actions_reserved'], evaluation['tool_calls_remaining']
    replay = tick(path, wake_id='demo-wake')
    with BodyLoop(path) as loop:
        host = BodyAPIHost.resume(loop, run_id='demo-wake')
        assert counters_before_replay == (loop.status()['actions_reserved'], host.evaluate()['tool_calls_remaining'])
        assert after == host.snapshot()
    summary = dict(schema='nasuraya-wakeup-demo-evidence/1', status=row['state'],
        real_host_clock_polling=True, generated_fixture=True, live_model_execution=False,
        api_network_requests=0, due_at_utc=due.isoformat(),
        initial_revision=before['revision'], final_revision=after['revision'],
        evaluation=evaluation, grant=grant, schedule=schedule['contract'], ticks=rows,
        terminal_replay_execution_started=replay['execution_started'], terminal_replay_state=replay['state'],
        permanent_service_installed=False)
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,sort_keys=True))
    return 0 if row['state']=='completed' else 1
