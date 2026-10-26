"""Explicit live verification of a saved API wakeup; never creates a grant/schedule."""
import json
from pathlib import Path
import time
from types import SimpleNamespace

from examples.nasuraya_agent_loop.agents_api import make_client,run_api
from .api_host import BodyAPIHost,digest
from .experience import packet
from .host import BodyLoop
from .scheduler import tick,schedules,TERMINAL,utcnow


def check(session,wake_id,output_dir):
    output=Path(output_dir)
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    with BodyLoop(session) as loop:
        row=next(r for r in schedules(loop) if r['id']==wake_id)
        if row['contract']['backend']!='api':
            raise ValueError('existing API schedule required')
        run_id=row['run_id']
        host=BodyAPIHost.resume(loop,run_id=run_id)
        before=host.snapshot()
        config=loop.config.copy()
        decisions_before=loop.engine.export()['decisions']
        memories_before=[]
        if loop.engine.db.execute("SELECT 1 FROM sqlite_master WHERE name='body_care_episodes'").fetchone():
            memories_before=[r[0] for r in loop.engine.db.execute('SELECT memo FROM body_care_episodes ORDER BY rowid')]
    attempts=[]
    contexts=[]
    checks=[]
    def runner(host,contract,timeout):
        event_path=output/('events-'+str(len(attempts))+'.jsonl')
        event_path.touch(exist_ok=False)
        host.journal.path=event_path  # Shared Journal object, not a wrapper reassignment.
        expected=packet(host)
        with make_client() as real:
            class Sessions:
                def __getattr__(self,name):return getattr(real.beta.agents.sessions,name)
                def create(self,**kwargs):
                    actual=json.loads(kwargs['input'].split('\n',1)[1])
                    assert actual==expected
                    contexts.append(dict(record_count=len(actual['records']),context_sha256=digest(actual),
                        source_decision_ids=[r['decision_id'] for r in actual['records']],
                        mismatched_outcomes=sum(not r['expected_outcome_matched'] for r in actual['records']),
                        input_verified_at_sdk_create=True))
                    return real.beta.agents.sessions.create(**kwargs)
            client=SimpleNamespace(beta=SimpleNamespace(agents=SimpleNamespace(sessions=Sessions())))
            result=run_api(host,client,model=contract['model'],max_calls=host.max_calls,
                           timeout_seconds=timeout,recovery='resume',max_reconnects=0,live_service=True)
        attempts.append(result)
        (output/('attempt-'+str(len(attempts))+'.json')).write_text(json.dumps(result,indent=2)+'\n')
        return result
    for _ in range(45):
        checked=utcnow().isoformat()
        result=tick(session,wake_id=wake_id,runner=runner)
        checks.append(dict(at_utc=checked,state=result['state'],attempts=result['attempts'],
                           execution_started=result['execution_started']))
        if result['state'] in TERMINAL:
            break
        time.sleep(1)
    with BodyLoop(session) as loop:
        host=BodyAPIHost.resume(loop,run_id=run_id)
        after=host.snapshot()
        evaluation=host.evaluate()
        current=loop.engine.export()['decisions']
        older=[r for r in current if r['id'] in {d['id'] for d in decisions_before}]
        assert older==decisions_before and config==loop.config
        if memories_before:
            assert memories_before==[r[0] for r in loop.engine.db.execute('SELECT memo FROM body_care_episodes ORDER BY rowid')]
        new=[r for r in current if r['id'] not in {d['id'] for d in decisions_before}]
        saved_transport=loop.engine.db.execute('SELECT * FROM body_api_transport WHERE run_id=?',(run_id,)).fetchone() if attempts else None
        transport=dict(saved_transport) if saved_transport else {}
    summary=dict(schema='nasuraya-live-experience-check/1',recorded_at_utc=utcnow().isoformat(),
        run_id=run_id,status=result['state'],model=row['contract']['model'],generated_fixture=True,
        real_host_clock_polling=True,live_api_verified=any(r['live_api_verified'] for r in attempts),
        initial_revision=before['revision'],final_revision=after['revision'],evaluation=evaluation,
        contexts=contexts,checks=checks,older_decisions_preserved=older==decisions_before,
        care_memories_preserved=True,base_config_preserved=True,
        new_decisions=[dict(id=d['id'],core_selected=d['selected_action'],
            body_actual=(d.get('actual_outcome') or {}).get('selected_action'),
            recalled_feedback_ids=d['recalled_feedback_ids']) for d in new],
        remote_state=transport.get('state'),remote_terminal_status=transport.get('terminal_status'),
        cleanup_status=attempts[-1]['cleanup_status'] if attempts else 'no_new_api_attempt',
        permanent_service_installed=False)
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,sort_keys=True))
    return 0 if result['state']=='completed' and summary['live_api_verified'] else 1
