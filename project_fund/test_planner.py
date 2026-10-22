"""All monetary values are synthetic test fixtures; no payments are made."""
from pathlib import Path
import tempfile
import unittest

from .planner import ProposalJournal, purchase_decision


class FundPlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'fixture.sqlite'
        self.journal = ProposalJournal(self.path)
        self.row = dict(entry_id='synthetic_quote', direction='proposed_expense', amount_minor=1234,
                        currency='USD', description='Synthetic fixture, not a real service quote',
                        source_ref='test:authored-fixture')

    def tearDown(self):
        self.journal.close()
        self.tmp.cleanup()

    def test_empty_summary_does_not_invent_a_bank_account_or_balance(self):
        summary = self.journal.summary()
        self.assertEqual(summary['entry_count'], 0)
        self.assertIsNone(summary['bank_balance'])
        self.assertIsNone(summary['settled_income'])
        self.assertFalse(summary['payments_enabled'])

    def test_restart_preserves_exact_proposal(self):
        first = self.journal.add(**self.row)
        self.journal.close()
        self.journal = ProposalJournal(self.path)
        self.assertEqual(self.journal.summary()['entries'], [first])

    def test_repeated_identical_request_is_idempotent(self):
        first = self.journal.add(**self.row)
        self.assertEqual(self.journal.add(**self.row), first)
        self.assertEqual(self.journal.summary()['entry_count'], 1)

    def test_same_id_cannot_change_amount_currency_or_direction(self):
        self.journal.add(**self.row)
        for changed in [dict(amount_minor=5678), dict(currency='EUR'), dict(direction='estimated_income')]:
            with self.assertRaises(ValueError): self.journal.add(**dict(self.row, **changed))
        self.assertEqual(self.journal.summary()['entry_count'], 1)

    def test_float_bool_negative_zero_and_overflow_are_rejected(self):
        for value in [1.5, True, -5, 0, 2**63]:
            with self.assertRaises(ValueError): self.journal.add(**dict(self.row, amount_minor=value))
        self.assertEqual(self.journal.summary()['entry_count'], 0)

    def test_currencies_are_separate_and_forecast_never_unlocks_payment(self):
        self.journal.add(**self.row)
        self.journal.add(**dict(self.row, entry_id='eur_fixture', currency='EUR', amount_minor=100))
        self.journal.add(**dict(self.row, entry_id='forecast_fixture', direction='estimated_income', amount_minor=99999999))
        summary = self.journal.summary()
        self.assertEqual(summary['planning_totals_by_currency']['USD'],
                         dict(estimated_income_minor=99999999, proposed_expense_minor=1234))
        self.assertEqual(summary['planning_totals_by_currency']['EUR']['proposed_expense_minor'], 100)
        self.assertIsNone(summary['settled_income'])
        self.assertFalse(purchase_decision()['allowed'])

    def test_actual_income_payment_and_missing_sources_are_rejected(self):
        for changes in [dict(direction='settled_income'), dict(direction='payment'), dict(source_ref=''),
                        dict(description=''), dict(currency='usd'), dict(entry_id='../escape')]:
            with self.assertRaises(ValueError): self.journal.add(**dict(self.row, **changes))


if __name__ == '__main__':
    unittest.main()
