"""Experimental open-set gate for the frozen PR195 decoder, NOT the PR196 runtime.

Inference accepts only a twelve-number feature tuple. Unknown truth/family labels
are unavailable to score(), calibrate() and infer(). All thresholds are fit on
separate KNOWN-only calibration episodes; no compound/pulse labels are used.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

from examples.tadash_interoception.model import Decoder
from examples.tadash_interoception.sensory import trial, transduce
from examples.tadash_interoception.state import observe, digest

MODEL_SHA = '3afd0c642a07759bcb637ab0d470b3c358c9e7109d811ce887ba4f65cb37c993'
ALPHA = 0.10
CALIBRATION_SEEDS = range(810000, 810800)
VALIDATION_SEEDS = range(820000, 820500)
FINAL_SEEDS = range(850000, 850700)
HISTORICAL_SEEDS = (range(710000, 710280), range(720000, 720140), range(750000, 750500))


def frozen_decoder():
    # PR196 owns the byte-pinned frozen artifact: load it directly on full checkouts.
    # Reconstruct only in a minimal standalone research archive lacking PR196.
    try:
        from examples.nasuraya_runtime.adapters import decoder as pinned_decoder
    except ModuleNotFoundError as exc:
        if exc.name not in ('examples.nasuraya_runtime', 'examples.nasuraya_runtime.adapters'):
            raise
    else:
        result = pinned_decoder()
        if result.fingerprint() != MODEL_SHA:
            raise ValueError('PR196 pinned PR195 decoder fingerprint mismatch')
        return result
    examples = []
    for seeds, training in ((HISTORICAL_SEEDS[0], True), (HISTORICAL_SEEDS[1], False)):
        for seed in seeds:
            stimulus, truth, _, _ = trial(seed, training=training)
            if truth['type'] == 'compound':
                continue
            state = observe(transduce(stimulus, seed=seed + 1777))
            label = 'none' if not truth['occurred'] else truth['location'] + ':' + truth['type']
            examples.append((state.features(), label, truth['intensity']))
    result = Decoder(examples, temperature=.5)
    if result.fingerprint() != MODEL_SHA:
        raise ValueError('PR195 decoder fingerprint mismatch; cannot evaluate')
    return result


def familiar_episode(seed):
    stimulus, truth, _, condition = trial(seed)
    if condition == 'novel':
        raise ValueError('novel stimulus forbidden in calibration and validation')
    features = observe(transduce(stimulus, seed=seed + 1777)).features()
    return {'seed': seed, 'features': features, 'condition': condition, 'truth': truth}


def known_rows(seeds):
    # Crucially skip novel cases BEFORE generating/transducing them.
    return [familiar_episode(s) for s in seeds if s % 5 != 4]


def signature(features):
    # Dimensionless spatial/channel shape plus a weak total-amplitude term.
    scale = max(.03, max(features))
    return tuple(x / scale for x in features)


def distance(a, b):
    a_sig, b_sig = signature(a), signature(b)
    shape = sum((x-y) ** 2 for x, y in zip(a_sig, b_sig)) / 12
    amplitude = (sum(a) - sum(b)) ** 2 / 144
    return shape + 0.12 * amplitude


@dataclass(frozen=True)
class Selection:
    occurred: bool
    stimulus_type: str
    location: str
    abstained: bool
    reason: str
    conformity_p: float | None
    old_confidence: float
    old_uncertain: bool


class SelectiveDecoder:
    def __init__(self, base, calibration):
        if base.fingerprint() != MODEL_SHA:
            raise ValueError('only frozen PR195 model may be wrapped')
        if calibration.get('schema') != 'tadash.open-set.calibration.v1':
            raise ValueError('invalid calibration schema')
        seal = calibration.get('sha256')
        if seal != digest({k: v for k, v in calibration.items() if k != 'sha256'}):
            raise ValueError('calibration fingerprint mismatch')
        if calibration['model_sha'] != MODEL_SHA or calibration['alpha'] != ALPHA:
            raise ValueError('model or confidence settings changed')
        self.base, self.calibration = base, calibration
        self.groups = {label: [features for features, k, _ in base.examples if k == label]
                       for label in ('none',) + tuple(r + ':' + k for r in ('left_palm', 'right_palm')
                                                for k in ('mechanical', 'thermal', 'vibration'))}

    def anomaly(self, features, label):
        pool = self.groups[label]
        if not pool:
            raise ValueError('missing class reference')
        return sorted(distance(features, candidate) for candidate in pool)[:3][-1]

    def infer(self, features):
        base = self.base.predict(features)
        if not base.occurred:
            return Selection(False, 'none', 'none', False, 'occurrence_below_half', None,
                             base.confidence, base.novelty_uncertain)
        label = base.location + ':' + base.stimulus_type
        scores = self.calibration['known_scores'].get(label)
        if not scores or len(scores) < 10:
            return Selection(True, 'unknown', 'unknown', True, 'insufficient_class_calibration', None,
                             base.confidence, base.novelty_uncertain)
        test_score = self.anomaly(features, label)
        # Split-conformal right-tail p-value. The zero-one decision is only about
        # compatibility with observed known-class support, NOT P(type is novel).
        p = (1 + sum(s >= test_score for s in scores)) / (len(scores) + 1)
        if p <= ALPHA:
            return Selection(True, 'unknown', 'unknown', True, 'out_of_known_support', p,
                             base.confidence, base.novelty_uncertain)
        return Selection(True, base.stimulus_type, base.location, False, 'known_support', p,
                         base.confidence, base.novelty_uncertain)


def calibrate(base):
    ref = SelectiveDecoder.__new__(SelectiveDecoder)
    ref.base = base
    ref.groups = {label: [f for f, k, _ in base.examples if k == label]
                  for label in ('none',) + tuple(r + ':' + k for r in ('left_palm','right_palm')
                                               for k in ('mechanical','thermal','vibration'))}
    buckets = {key: [] for key in ref.groups if key != 'none'}
    counts = {'episodes_total_known': 0, 'accepted_correct_known': 0,
              'excluded_wrong_prediction': 0, 'no_stimulus': 0}
    for row in known_rows(CALIBRATION_SEEDS):
        counts['episodes_total_known'] += 1
        p = base.predict(row['features'])
        if not row['truth']['occurred']:
            counts['no_stimulus'] += 1
        elif p.occurred and p.location == row['truth']['location'] and p.stimulus_type == row['truth']['type']:
            label = p.location + ':' + p.stimulus_type
            buckets[label].append(ref.anomaly(row['features'], label))
            counts['accepted_correct_known'] += 1
        else:
            counts['excluded_wrong_prediction'] += 1
    if any(len(v) < 10 for v in buckets.values()):
        raise ValueError('insufficient per-class known calibration')
    frozen = {'schema': 'tadash.open-set.calibration.v1', 'alpha': ALPHA,
              'model_sha': MODEL_SHA, 'method': 'class-conditional split conformal k3 shape-distance v1',
              'calibration_seeds': [CALIBRATION_SEEDS.start, CALIBRATION_SEEDS.stop - 1],
              'validation_seeds': [VALIDATION_SEEDS.start, VALIDATION_SEEDS.stop - 1],
              'final_seeds': [FINAL_SEEDS.start, FINAL_SEEDS.stop - 1],
              'counts': counts,
              'known_scores': {k: sorted(v) for k, v in sorted(buckets.items())},
              'no_novel_used_for_calibration': True,
              'original_test_not_reused_for_optimization': True}
    frozen['sha256'] = digest(frozen)
    return frozen


def decide(selection):
    """Counterfactual *type-specific* simulation, never dispatched to PR196."""
    if not selection.occurred: return 'continue'
    if selection.abstained: return 'observe'
    return {'mechanical': 'stabilize', 'thermal': 'cool', 'vibration': 'inspect'}[selection.stimulus_type]


def action_cost(guess, truth):
    """Author-defined illustrative loss, not real health/robotic task reward."""
    expected = ('continue' if not truth['occurred'] else 'observe' if truth['type'] not in
                ('mechanical', 'thermal', 'vibration') else
                {'mechanical': 'stabilize', 'thermal': 'cool', 'vibration': 'inspect'}[truth['type']])
    if guess == expected: return 0
    if guess == 'observe' and expected != 'observe': return 1
    if expected == 'observe': return 5  # acting on false known-type certainty
    if expected == 'continue': return 3
    return 4


def comparison(rows, base, gate):
    summary = {'episodes': len(rows), 'known': 0, 'unknown': 0, 'none': 0,
               'occurrence_correct': 0,
               'baseline': {'correct_three_way': 0, 'correct_known_type': 0, 'justified_abstention': 0,
                            'false_certainty_unknown': 0, 'unnecessary_abstention_known': 0,
                            'false_positive_none': 0, 'decision_cost_total': 0},
               'selective': {'correct_three_way': 0, 'correct_known_type': 0, 'justified_abstention': 0,
                             'false_certainty_unknown': 0, 'unnecessary_abstention_known': 0,
                             'false_positive_none': 0, 'decision_cost_total': 0},
               'conditions': {}}
    for row in rows:
        truth, f = row['truth'], row['features']
        old = base.predict(f)
        new = gate.infer(f)
        old_choice = Selection(old.occurred, old.stimulus_type, old.location, False, 'legacy', None,
                               old.confidence, old.novelty_uncertain)
        kind = ('none' if not truth['occurred'] else 'known' if truth['type'] in
                ('mechanical', 'thermal', 'vibration') else 'unknown')
        summary[kind] += 1
        summary['occurrence_correct'] += (old.occurred == truth['occurred'])
        bucket = summary['conditions'].setdefault(row['condition'], {'n': 0,
                    'baseline_correct': 0, 'selective_correct': 0, 'selective_unknown': 0,
                    'baseline_cost': 0, 'selective_cost': 0})
        bucket['n'] += 1
        for name, selection in (('baseline', old_choice), ('selective', new)):
            s = summary[name]
            correct = ((kind == 'none' and not selection.occurred) or
                       (kind == 'unknown' and selection.abstained and selection.occurred) or
                       (kind == 'known' and selection.occurred and not selection.abstained and
                        selection.stimulus_type == truth['type'] and selection.location == truth['location']))
            s['correct_three_way'] += int(correct)
            s['correct_known_type'] += int(kind == 'known' and selection.occurred and
                                           selection.stimulus_type == truth['type'] and not selection.abstained)
            s['justified_abstention'] += int(kind == 'unknown' and selection.abstained)
            s['false_certainty_unknown'] += int(kind == 'unknown' and selection.occurred and not selection.abstained)
            s['unnecessary_abstention_known'] += int(kind == 'known' and selection.abstained)
            s['false_positive_none'] += int(kind == 'none' and selection.occurred)
            cost = action_cost(decide(selection), truth)
            s['decision_cost_total'] += cost
            bucket[name + '_correct'] += int(correct)
            bucket[name + '_cost'] += cost
            if name == 'selective': bucket['selective_unknown'] += int(selection.abstained)
    for name in ('baseline', 'selective'):
        s=summary[name]
        s['accuracy_three_way'] = s['correct_three_way'] / len(rows)
        s['mean_counterfactual_cost'] = s['decision_cost_total'] / len(rows)
        s['unknown_abstention_rate'] = s['justified_abstention'] / summary['unknown'] if summary['unknown'] else None
        s['known_type_coverage'] = (summary['known'] - s['unnecessary_abstention_known']) / summary['known'] if summary['known'] else None
    return summary
