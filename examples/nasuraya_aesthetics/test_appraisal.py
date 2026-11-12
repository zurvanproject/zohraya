from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

from .appraisal import appraise, reference
from .fixtures import observation, similarity


class AppraisalTests(unittest.TestCase):
    def test_beauty_is_identical_under_self_other_relabeling(self):
        own = appraise(observation())
        other = appraise(observation(subject='other'))
        self.assertEqual(own['report']['aesthetic_rating'], other['report']['aesthetic_rating'])
        self.assertGreater(own['social_event']['signals']['satisfaction'],
                           other['social_event']['signals']['satisfaction'])

    def test_unknown_self_needs_verification_even_when_beautiful(self):
        result = appraise(observation(image_sha256='1'*64))
        self.assertEqual(result['report']['recommendation'], 'verify_identity')
        self.assertIsNone(result['report']['identity']['similarity'])

    def test_beautiful_different_identity_is_not_adopted(self):
        obs = observation(image_sha256='1'*64, beauty=1.)
        obs['identity_similarity'] = similarity(.2)
        result = appraise(obs)
        self.assertEqual(result['report']['approved_reference'], reference())
        self.assertIn('identity_drift', result['report']['reasons'])

    def test_missing_beauty_is_not_fabricated(self):
        result = appraise(observation(beauty=None))
        self.assertIsNone(result['report']['aesthetic_rating'])
        self.assertEqual(result['social_event']['signals']['excellence'], 0.)

    def test_zero_confidence_rating_has_no_aesthetic_effect(self):
        result = appraise(observation(confidence=0.))
        self.assertEqual(result['social_event']['signals']['excellence'], 0.)
        self.assertEqual(result['social_event']['signals']['satisfaction'], .25)

    def test_low_identity_confidence_requests_verification(self):
        obs = observation(image_sha256='1'*64)
        obs['identity_similarity'] = similarity(.99, confidence=.2)
        self.assertEqual(appraise(obs)['report']['recommendation'], 'verify_identity')

    def test_aesthetic_signals_never_assign_merit_shame_or_relationship(self):
        for beauty in (0., .5, 1.):
            result = appraise(observation(beauty=beauty))
            signals = result['social_event']['signals']
            for key in ('self_devaluation', 'reliability', 'achievement', 'appeal', 'moral_example'):
                self.assertNotIn(key, signals)
            self.assertEqual(result['report']['self_worth_change'], 0.)
            self.assertEqual(result['report']['ethical_merit_change'], 0.)

    def test_declared_proportion_issue_survives_high_beauty(self):
        obs = observation(beauty=1.)
        obs['ratings']['proportion'] = dict(value=.2, confidence=1., kind='operator_rating',
                                          source_ref='fixture://proportion')
        self.assertEqual(appraise(obs)['report']['recommendation'], 'review_proportions')

    def test_own_versus_other_is_declared_not_inferred_from_prettiness(self):
        result = appraise(observation(subject='unknown'))
        self.assertEqual(result['report']['observation']['subject'], 'unknown')
        self.assertEqual(result['report']['subject_attribution'], 'caller_declared')

    def test_rejects_nonfinite_and_bool_ratings(self):
        for bad in (float('nan'), float('inf'), True, -.1, 1.1, '0.9'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                appraise(observation(beauty=bad))

    def test_rejects_missing_rating_source_or_unknown_fields(self):
        obs = observation(); del obs['ratings']['beauty']['source_ref']
        with self.assertRaises(ValueError): appraise(obs)
        obs = observation(); obs['intelligence'] = .9
        with self.assertRaises(ValueError): appraise(obs)

    def test_identity_estimate_must_bind_current_reference(self):
        obs = observation(image_sha256='1'*64); obs['identity_similarity'] = similarity(.9)
        obs['identity_similarity']['reference_sha256'] = '2'*64
        with self.assertRaises(ValueError): appraise(obs)

    def test_contradictory_reference_hash_and_similarity_rejected(self):
        obs = observation(); obs['identity_similarity'] = similarity(.2)
        with self.assertRaises(ValueError): appraise(obs)

    def test_only_supplied_actual_bytes_are_reported_verified(self):
        data = b'fixture image bytes, not a real face'
        ref = reference(); ref['sha256'] = hashlib.sha256(data).hexdigest()
        obs = observation(image_sha256=ref['sha256'])
        self.assertFalse(appraise(obs, approved_reference=ref)['report']['image_bytes_verified'])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fixture.bin'; path.write_bytes(data)
            report = appraise(obs, approved_reference=ref, image_path=path)['report']
            self.assertTrue(report['image_bytes_verified'])
            self.assertEqual(report['identity']['status'], 'exact_reference_bytes')
            obs['image_sha256'] = '1'*64
            with self.assertRaises(ValueError): appraise(obs, approved_reference=ref, image_path=path)

    def test_appraisal_does_not_mutate_inputs_or_reference(self):
        obs = observation(); ref = reference(); before = deepcopy((obs, ref))
        result = appraise(obs, approved_reference=ref)
        result['report']['approved_reference']['character'] = 'changed'
        self.assertEqual((obs, ref), before)

    def test_reference_requires_explicit_approval(self):
        ref = reference(); ref['status'] = 'candidate'
        with self.assertRaises(ValueError): appraise(observation(), approved_reference=ref)
