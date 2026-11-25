"""Health probe: success means a recent poll, even if GitHub is temporarily down."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from .agent import parse_interval


def healthy(status_path, interval, now=None):
    now = now or datetime.now(timezone.utc)
    status = json.loads(Path(status_path).read_text(encoding='utf-8'))
    if status.get('schema') != 'nasurayaza-watch/1':
        return False
    at = datetime.fromisoformat(status['at'])
    return at.tzinfo is not None and 0 <= (now - at).total_seconds() <= 3 * interval + 90


if __name__ == '__main__':
    interval = parse_interval(os.environ.get('POLL_SECONDS', '900'))
    try:
        ready = healthy(Path(os.environ.get('NASURAYAZA_DATA', '/data')) / 'status.json', interval)
    except (OSError, ValueError, KeyError, TypeError):
        ready = False
    raise SystemExit(0 if ready else 1)
