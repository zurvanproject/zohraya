"""Read-only, nonsensitive summary of the bounded Nasuraya 24-hour study."""
import json
import os
import time
from pathlib import Path

root = Path(os.getenv('PROGRAMDATA') or '/tmp') / 'NasurayaBridge' / 'nasu_24h_20261109_v1'
state = root / 'state.json'
if not state.exists():
    summary = 'STATE=NOT_STARTED'
else:
    try:
        data = json.loads(state.read_text(encoding='ascii'))
        total = data.get('total') or {}
        age = max(0, int((time.time() - float(data.get('heartbeat', data.get('start_epoch', time.time())))) / 60))
        left = max(0, int((float(data.get('deadline', time.time())) - time.time()) / 60))
        name = str(data.get('status', 'unknown')).upper()
        if name not in ('RUNNING','DEGRADED','STOPPED','REVIEW_REQUIRED','COMPLETED','INCOMPLETE_NO_RESULTS','LAUNCHING','LAUNCH_FAILED'):
            name = 'UNKNOWN'
        summary = (f"STATE={name};CYCLES={int(total.get('cycles',0))};"
                   f"ROLYEL={int(total.get('rolyel_trials',0))};"
                   f"BAD={int(total.get('unsafe',0))};"
                   f"TESTS={int(total.get('tests_passed',0))};"
                   f"TF={int(total.get('tests_failed',0))};"
                   f"BODYTOY={int(total.get('toy_trials',0))};"
                   f"AUDIT={int((root/'body_audit.json').exists())};"
                   f"STALE_MIN={age};LEFT_MIN={left}")
    except (OSError, ValueError, TypeError):
        summary = 'STATE=READ_ERROR'
print(json.dumps({'status':'ok','summary':summary},separators=(',',':')))
