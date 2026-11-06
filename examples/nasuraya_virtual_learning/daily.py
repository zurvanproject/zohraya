"""Finite daily ritual practice on the synthetic, offline NVLE fixture only.

Exactly three explicit event IDs per UTC date; repeated invocation is replay-safe.
No BodyLoop step, external API, network, or unfettered autonomy.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path

from .engine import LESSONS, connect, status, train


def run_day(db: Path, on_date: date | None = None) -> dict:
    day = on_date or datetime.now(timezone.utc).date()
    if not isinstance(day, date):
        raise ValueError("expected explicit date, or current UTC date")
    db = Path(db).expanduser()
    if db.is_symlink():
        raise ValueError("refuse symbolic SQLite path")
    db.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with connect(db) as conn:
        db.chmod(0o600)
        records = []
        for context in LESSONS:
            event_id = f"daily-{day:%Y%m%d}-{context}"
            result = train(conn, event_id, context)
            records.append({
                "event_id": event_id,
                "context": context,
                "replayed": result["replayed"],
                "synthetic_reward": result["receipt"]["reward"],
            })
        after = status(conn)
    return {
        "mode": "offline_synthetic_daily_ritual",
        "utc_date": day.isoformat(),
        "events": records,
        "total_synthetic_episodes": after["episodes"],
        "synthetic_holdout_score": f"{after['holdout']['correct']}/{after['holdout']['total']}",
        "native_body_actions": 0,
        "external_api_calls": 0,
        "subjective_experience_inferred": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Finite daily synthetic ritual; offline")
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(run_day(args.db), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
