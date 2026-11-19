"""Operator-initiated graceful stop for the isolated 24-hour research worker."""
import json
import os
from pathlib import Path
root = Path(os.getenv('PROGRAMDATA') or '/tmp') / 'NasurayaBridge' / 'nasu_24h_20261109_v1'
if root.exists() and (root / 'state.json').exists():
    (root / 'STOP').write_text('stop-requested', encoding='ascii')
    message = 'STOP=REQUESTED'
else:
    message = 'STOP=NO_ACTIVE_RUN'
print(json.dumps({'status':'ok','summary':message},separators=(',',':')))
