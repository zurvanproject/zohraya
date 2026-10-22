"""Cold-process terminal replay with API, input building and body effects forbidden."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from examples.nasuraya_agent_loop.agents_api import run_api
from .api_host import BodyAPIHost
from .host import BodyLoop, UnifiedBody


def check(session, run_id, output_dir, *, fresh_process=False):
    output = Path(output_dir)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    requests = []
    class ForbiddenSessions:
        def __getattr__(self, name):
            requests.append(name)
            raise AssertionError('API forbidden during terminal replay')
    def forbidden_input():
        raise AssertionError('initial input must not be rebuilt')
    with BodyLoop(session) as loop:
        host = BodyAPIHost.resume(loop, run_id=run_id)
        row = loop.engine.db.execute('SELECT * FROM body_api_transport WHERE run_id=?', (run_id,)).fetchone()
        if not row or row['terminal_status'] != 'completed' or row['state'] != 'deleted':
            raise ValueError('completed, cleaned-up saved API mission required')
        before = host.snapshot(), host.evaluate(), loop.engine.export()
        host.continuation_input = forbidden_input
        client = SimpleNamespace(beta=SimpleNamespace(agents=SimpleNamespace(sessions=ForbiddenSessions())))
        with patch.object(UnifiedBody, 'cycle', side_effect=AssertionError('body replay forbidden')):
            result = run_api(host, client, model=row['model'], max_calls=host.max_calls,
                             recovery='resume', max_reconnects=0)
        after = host.snapshot(), host.evaluate(), loop.engine.export()
        assert result['status'] == 'completed' and before == after and requests == []
    evidence = dict(schema='nasuraya-terminal-replay-check/1', run_id=run_id,
                    status=result['status'], kind=result['api_recovery']['kind'],
                    fresh_process=fresh_process, api_requests=len(requests), new_actions=0,
                    new_tool_calls=0, state_and_history_preserved=True,
                    initial_input_rebuilt=False, live_api_verified=False,
                    note='saved completion read; no new live mission')
    (output / 'summary.json').write_text(json.dumps(evidence, indent=2)+'\n')
    print(json.dumps(evidence, sort_keys=True))
    return 0
