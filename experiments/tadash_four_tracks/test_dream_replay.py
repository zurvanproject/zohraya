"""All fixtures are authored numerical data, NOT native simulator execution."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from .dream_replay import (AUDIT_CAPS, evaluate, main,
                           read_native_rows, train_delta, validate_row)


def example_rows(*, reverse=False):
    rows = []
    # Each side has 6 disjoint episodes, with 2 events per episode.
    for context in ('baseline', 'post_walk'):
        for action in ('observe', 'slow_breath'):
            for episode in range(3):
                for step in range(2):
                    before = dict(arousal=.5 + .005 * episode,
                                  pain=.1, fatigue=.2, energy=.8, hydration=.7)
                    after = before.copy()
                    change = -.02 if action == 'observe' else -.04
                    if reverse and context == 'post_walk':
                        change = -change
                    after['arousal'] += change
                    row = {'event_id': f'{context}-{action}-{episode}-{step}',
                           'episode_id': f'{context}-{action}-{episode}',
                           'context': context, 'synthetic': True,
                           'requested': action, 'actual': action,
                           'before': before, 'after': after,
                           'native_audit': {k: 0.0 for k in AUDIT_CAPS}}
                    rows.append(row)
    return rows


class DreamLedgerTest(unittest.TestCase):
    def test_rehearsal_is_imagined_and_closed_even_when_score_improves(self):
        report, dreams, memory = evaluate(example_rows(), 'a'*64)
        self.assertTrue(report['candidate_beats_persistence_by_10pct'])
        self.assertFalse(report['promotion_authorized'])
        self.assertGreater(len(dreams), 0)
        self.assertTrue(all(not d['allowed_to_train_or_act'] for d in dreams))
        self.assertTrue(all(m['imagined'] is False for m in memory))
        self.assertEqual(report['native_actions_executed'], 0)
        self.assertEqual(report['scored_rows'], 12)

    def test_bad_model_reports_negative(self):
        report, _, _ = evaluate(example_rows(reverse=True), 'a'*64)
        self.assertFalse(report['candidate_beats_persistence_by_10pct'])
        self.assertGreater(report['model_mae'], report['persistence_mae'])

    def test_dream_roots_never_include_holdout(self):
        rows = example_rows(); report, dreams, _ = evaluate(rows, 'b'*64)
        held = {r['event_id'] for r in rows if r['context'] == 'post_walk'}
        self.assertFalse({d['root_observed_event'] for d in dreams} & held)
        self.assertEqual(report['evaluation_episode_count'], 6)

    def test_deterministic_replay(self):
        a = evaluate(example_rows(), 'c'*64)
        b = evaluate(example_rows(), 'c'*64)
        self.assertEqual(a, b)

    def test_wrong_evidence_hash(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t)/'input.jsonl'
            path.write_text('\n'.join(json.dumps(r) for r in example_rows())+'\n')
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                read_native_rows(path, '0'*64)

    def test_read_and_cli(self):
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t); path = folder/'input.jsonl'
            raw = ''.join(json.dumps(r, sort_keys=True)+'\n' for r in example_rows()).encode()
            path.write_bytes(raw); sha = hashlib.sha256(raw).hexdigest()
            source, got_sha = read_native_rows(path, sha)
            self.assertEqual(len(source), 24)
            self.assertEqual(got_sha, sha)
            out = folder/'new_dream'
            self.assertEqual(main(['--source',str(path),'--expected-sha256',sha,
                                   '--output-dir',str(out)]),0)
            self.assertTrue((out/'report.json').exists())
            with self.assertRaises(FileExistsError):
                main(['--source',str(path),'--expected-sha256',sha,
                      '--output-dir',str(out)])

    def test_non_native_or_unexpected_fields_rejected(self):
        row = example_rows()[0]
        for mutate in (lambda x:x.update(synthetic=False),
                       lambda x:x.update(private='not allowed'),
                       lambda x:x.update(before={**x['before'], 'subjective_feeling': .5}),
                       lambda x:x['native_audit'].update(energy_error_J=1)):
            changed = copy.deepcopy(row); mutate(changed)
            with self.assertRaises(ValueError): validate_row(changed)

    def test_nan_bool_invalid(self):
        for value in [True, float('nan'), float('inf'), -0.1, 1.1]:
            row = example_rows()[0]; row['before']['arousal'] = value
            with self.assertRaises(ValueError): validate_row(row)

    def test_native_veto_never_trains_or_dreams(self):
        rows = example_rows()
        rows[0]['actual'] = 'protect'
        train, _, model = train_delta(rows)
        self.assertEqual(model['observe']['count'], 5)
        report, dreams, _ = evaluate(rows, 'd'*64)
        self.assertNotIn(rows[0]['event_id'], {d['root_observed_event'] for d in dreams})
        self.assertFalse(report['promotion_authorized'])

    def test_protective_outcome_prioritized_in_observed_memory(self):
        rows = example_rows()
        rows[0]['actual'] = 'protect'
        _, _, memory = evaluate(rows, 'a'*64)
        self.assertEqual(memory[0]['event_id'], rows[0]['event_id'])
        self.assertTrue(memory[0]['protection_or_veto_observed'])

    def test_episode_leakage_rejected(self):
        rows = example_rows()
        rows[-1]['episode_id'] = rows[0]['episode_id']
        with self.assertRaisesRegex(ValueError, 'disjoint'):
            evaluate(rows, 'e'*64)

    def test_out_of_domain_abstain(self):
        rows = example_rows(); rows[-1]['before']['energy'] = .2
        report, _, _ = evaluate(rows, 'f'*64)
        self.assertEqual(len(report['abstentions']),1)
        self.assertFalse(report['candidate_beats_persistence_by_10pct'])

    def test_only_expected_contexts(self):
        row = example_rows()[0]; row['context'] = 'world'
        with self.assertRaises(ValueError): validate_row(row)

    def test_duplicate_events_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t)/'input.jsonl'
            r=example_rows()[0]
            raw=(json.dumps(r)+'\n'+json.dumps(r)+'\n').encode()
            path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, 'duplicate native event'):
                read_native_rows(path,hashlib.sha256(raw).hexdigest())

    def test_duplicate_json_key_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'input.jsonl'
            r=json.dumps(example_rows()[0])
            r=r.replace('"synthetic": true', '"synthetic": true, "synthetic": true')
            raw=(r+'\n').encode(); p.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, 'duplicate JSON'):
                read_native_rows(p,hashlib.sha256(raw).hexdigest())

    def test_no_silent_promotion_from_audit(self):
        rows=example_rows()
        rows[0]['native_audit']['energy_error_J'] = 1e-3
        with self.assertRaises(ValueError):
            validate_row(rows[0])


if __name__ == '__main__':
    unittest.main()
