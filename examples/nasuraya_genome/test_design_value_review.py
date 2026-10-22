from copy import deepcopy
import unittest
from .design_value_review import PARENT, classify, review, verify


class DesignValueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = PARENT.read_bytes()
        cls.result = review()

    def test_no_function_gain_is_pending_aesthetic_judgment_not_rejection(self):
        p = self.result['payload']
        row = p['candidates']['cosmetic_only']
        self.assertEqual(row['status'], 'awaiting_user_aesthetic_review')
        self.assertEqual(row['aesthetic_assessment']['verdict'], 'unrated')
        self.assertFalse(row['aesthetic_rejected_for_lack_of_function'])
        self.assertIsNone(p['specific_fur_length_preference'])

    def test_explicit_aesthetic_value_can_retain_a_functionally_neutral_option(self):
        # Synthetic unit verdicts; no approval by the real user is asserted.
        functional = self.result['payload']['candidates']['cosmetic_only']['functional_assessment']
        row = classify(functional, dict(verdict='approved', source='synthetic unit-test user verdict'))
        self.assertEqual(row['status'], 'aesthetic_option_retained')
        declined = classify(functional, dict(verdict='rejected', source='synthetic unit-test user verdict'))
        self.assertEqual(declined['status'], 'declined_by_user_aesthetic_review')
        with self.assertRaises(ValueError):
            classify(functional, dict(verdict='approved', source=''))

    def test_aesthetic_rating_does_not_remove_mechanical_guard_reasons(self):
        row = classify(dict(status='rejected', reasons=['pressure_ceiling_exceeded']),
                       dict(verdict='approved', source='synthetic unit-test user verdict'))
        self.assertEqual(row['functional_guard_reasons'], ['pressure_ceiling_exceeded'])
        self.assertEqual(row['aesthetic_assessment']['verdict'], 'approved')
        self.assertFalse(row['native_apply_allowed'])

    def test_functional_foot_proposal_history_and_review_survive_reload(self):
        self.assertEqual(self.result['payload']['retained_foot_design'], 'foot_plus_2_percent')
        self.assertEqual(self.result['payload']['body_trials_performed'], 0)
        self.assertEqual(PARENT.read_bytes(), self.original)
        self.assertTrue(verify(deepcopy(self.result)))
        bad = deepcopy(self.result)
        bad['payload']['specific_fur_length_preference'] = 4
        with self.assertRaises(ValueError):
            verify(bad)
