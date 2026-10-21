"""Persistent planning journal, deliberately incapable of moving money.

All entries are estimates/proposals. They never establish settled revenue,
bank balance, verified receipts, spending authority, or an existing account.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3


class ProposalJournal:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('''CREATE TABLE IF NOT EXISTS proposals (
            id TEXT PRIMARY KEY,
            direction TEXT NOT NULL CHECK(direction IN ('estimated_income','proposed_expense')),
            amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
            currency TEXT NOT NULL,
            description TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            created_at TEXT NOT NULL
        )''')
        self.db.commit()

    def close(self):
        self.db.close()

    def add(self, entry_id, direction, amount_minor, currency, description, source_ref):
        if not isinstance(entry_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', entry_id):
            raise ValueError('invalid proposal id')
        if direction not in ('estimated_income', 'proposed_expense'):
            raise ValueError('only estimated income or proposed expense is supported')
        if type(amount_minor) is not int or not 0 < amount_minor < 2**63:
            raise ValueError('positive integer minor units required; no float or bool')
        if not isinstance(currency, str) or not re.fullmatch('[A-Z]{3}', currency):
            raise ValueError('explicit three-letter currency label required')
        for value, limit in [(description, 2000), (source_ref, 500)]:
            if not isinstance(value, str) or not 0 < len(value.strip()) <= limit:
                raise ValueError('description and source reference required within bounds')
        fields = dict(id=entry_id, direction=direction, amount_minor=amount_minor,
                      currency=currency, description=description, source_ref=source_ref)
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO proposals VALUES (?,?,?,?,?,?,?)',
                (*fields.values(), datetime.now(timezone.utc).isoformat()))
            row = dict(self.db.execute('SELECT * FROM proposals WHERE id=?', (entry_id,)).fetchone())
            if any(row[k] != v for k, v in fields.items()):
                raise ValueError('proposal id already bound to different content')
        return row

    def summary(self):
        # Python integer sums; never mix currency labels or infer a bank balance.
        rows = [dict(r) for r in self.db.execute('SELECT * FROM proposals ORDER BY id')]
        totals = {}
        for row in rows:
            totals.setdefault(row['currency'], dict(estimated_income_minor=0, proposed_expense_minor=0))
            totals[row['currency']][row['direction']+'_minor'] += row['amount_minor']
        return dict(schema='nasuraya-fund-planning-summary/1', entry_count=len(rows),
                    planning_totals_by_currency=totals, entries=rows,
                    settled_income=None, bank_balance=None,
                    payments_enabled=False, financial_connection='not_implemented',
                    warning='All amounts are unverified estimates/proposals, not money or spending authority.')


def purchase_decision():
    # No configuration, forecast, proposal or ledger entry can unlock payment.
    return dict(allowed=False, reason='no_custodian_or_financial_execution_integration',
                monthly_authorized_spending_minor=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--add-json', help='local JSON proposal; no remote fetch or payment')
    args = parser.parse_args()
    journal = ProposalJournal(args.db)
    try:
        if args.add_json:
            journal.add(**json.loads(Path(args.add_json).read_text()))
        print(json.dumps(dict(summary=journal.summary(), purchase=purchase_decision()), ensure_ascii=False, indent=2))
    finally:
        journal.close()
