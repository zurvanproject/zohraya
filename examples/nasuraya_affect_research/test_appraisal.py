"""Pure contract tests. Constructed rows are labelled, not physical measurements."""
from copy import deepcopy
import unittest
from .appraisal import digest, event_from_result, need_load


def fixture(*, outcome=True, p=.9, before=None, after=None):
    q = [.8, .9, .1, .0, .1, 1.]
    def obs(q, h):
        return dict(mode='read_only_research', source_checkpoint_sha256=h*64, sensory=dict(q=q))
    return dict(historical_native_cycles=1, preferred_action='walk',
        native_receipt=dict(actual_action='walk' if outcome else 'protect'),
        research_before=obs(q if before is None else before, 'a'),
        research_after=obs(q if after is None else after, 'b'),
        prediction=dict(schema='nasuraya-outcome-calibration/1',
            target='preferred_action_executed_by_native_body',
            role='report_only_no_decision_or_authority_writeback',
            domain=dict(action='walk', duration_s=.1), raw_confidence=p, calibrated_confidence=p,
            raw_brier=(p-int(outcome))**2, calibrated_brier=(p-int(outcome))**2,
            outcome=outcome, outcome_source='native-decision://constructed-test/'+('c'*64)))


class AppraisalContracts(unittest.TestCase):
    def test_completed_success_has_specific_scope(self):
        event, facts = event_from_result(fixture())
        self.assertEqual(event['signals']['success'], 1.)
        self.assertIn('NOT task/route completion', facts['outcome_scope'])

    def test_native_veto_is_not_success(self):
        event, facts = event_from_result(fixture(outcome=False, p=.95))
        self.assertEqual(event['signals']['success'], 0.)
        self.assertEqual(event['signals']['negative_prediction'], .95)
        self.assertEqual(facts['forecast_error'], .95)

    def test_no_body_change_is_not_relief(self):
        event, _ = event_from_result(fixture())
        self.assertEqual(event['signals']['threat_removed'], 0.)

    def test_body_recovery_is_separate_from_task_success(self):
        event, facts = event_from_result(fixture(outcome=False, after=[.9, 1., .05, 0., .05, 1.]))
        self.assertGreater(facts['body_need_change'], 0.)
        self.assertEqual(event['signals']['success'], 0.)

    def test_deterioration_has_no_false_relief(self):
        event, facts = event_from_result(fixture(after=[.7,.8,.2,.4,.3,.8]))
        self.assertLess(facts['body_need_change'], 0.)
        self.assertEqual(event['signals']['threat_removed'], 0.)

    def test_praise_and_emotion_prose_do_not_change_evidence(self):
        a = fixture(outcome=False); b = deepcopy(a)
        b.update(praise='wonderful success', mood='joy', felt_relief=1.)
        self.assertEqual(event_from_result(a), event_from_result(b))

    def test_replay_transport_flags_do_not_create_new_episode(self):
        a = fixture(); b = dict(a, replayed=True, this_call_native_cycles=0)
        self.assertEqual(event_from_result(a), event_from_result(b))

    def test_unknown_outcome_rejects(self):
        a=fixture(); a['prediction']['outcome']=None
        with self.assertRaises(ValueError): event_from_result(a)

    def test_no_native_cycle_rejects(self):
        for x in (0, 2, True, 1.):
            with self.subTest(x=x), self.assertRaises(ValueError):
                event_from_result(dict(fixture(), historical_native_cycles=x))

    def test_spoofed_success_rejects(self):
        a=fixture(); a['native_receipt']['actual_action']='protect'
        with self.assertRaises(ValueError): event_from_result(a)

    def test_forecast_contract_cannot_be_replaced(self):
        for key in ('schema', 'target', 'role'):
            a=fixture(); a['prediction'][key]='changed'
            with self.subTest(key=key), self.assertRaises(ValueError): event_from_result(a)

    def test_domain_mismatch_rejects(self):
        a=fixture(); a['prediction']['domain']['action']='observe'
        with self.assertRaises(ValueError): event_from_result(a)

    def test_invalid_prior_rejects(self):
        for x in (True, '0.8', float('nan'), float('inf'), -1., 1.1):
            a=fixture(); a['prediction']['raw_confidence']=x
            with self.subTest(x=x), self.assertRaises(ValueError): event_from_result(a)

    def test_invalid_body_inputs_reject(self):
        for x in (True, float('nan'), -1., 1.1):
            a=fixture(); a['research_after']['sensory']['q'][0]=x
            with self.subTest(x=x), self.assertRaises(ValueError): event_from_result(a)

    def test_invalid_duration_rejects(self):
        for x in (0., .15, 2., True, float('inf')):
            a=fixture(); a['prediction']['domain']['duration_s']=x
            with self.subTest(x=x), self.assertRaises(ValueError): event_from_result(a)

    def test_unmatched_error_rejects(self):
        a=fixture(); a['prediction']['calibrated_brier']=.9
        with self.assertRaises(ValueError): event_from_result(a)

    def test_provenance_required(self):
        a=fixture(); a['prediction']['outcome_source']='I feel successful'
        with self.assertRaises(ValueError): event_from_result(a)

    def test_no_mutation_on_valid_or_invalid(self):
        for a in (fixture(), dict(fixture(), historical_native_cycles=0)):
            before=digest(a)
            try: event_from_result(a)
            except ValueError: pass
            self.assertEqual(digest(a), before)

    def test_same_binary_uncertainty_for_complementary_priors(self):
        _, a=event_from_result(fixture(p=.25)); _, b=event_from_result(fixture(p=.75))
        self.assertEqual(a['prior_uncertainty'], b['prior_uncertainty'])

    def test_need_load_is_bounded_on_corners(self):
        import itertools
        for q in itertools.product((0.,1.), repeat=6):
            self.assertGreaterEqual(need_load(q), 0.)
            self.assertLessEqual(need_load(q), 6.)

if __name__ == '__main__':
    unittest.main()
