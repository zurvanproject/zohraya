"""Audit a receipt-trained exact-action observer on a prespecified fatigue panel.

Run with python3 -m examples.nasuraya_body_loop.rare_breath_audit --output-dir NEW_DIR.
A new SQLite session is used for every single-step simulation.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import sys
import tempfile

from .__main__ import ROOT, SOURCE, verified_sources

FIT_FATIGUE = (.480, .510, .518, .523, .530, .538, .543, .548, .558, .580)
TEST_FATIGUE = (.488, .513, .519, .521, .525, .533, .541, .544, .546, .552, .574)


def panel():
    cases = []
    for group, points, backgrounds in (
        ('fit', FIT_FATIGUE, ((.04, .34), (.12, .61))),
        ('interpolation', TEST_FATIGUE, ((.08, .455),)),
        ('stress', (.51, .535), ((.78, .455), (.08, .93))),
    ):
        for fatigue in points:
            for pain, sleep in backgrounds:
                cases.append(dict(id=f'breath-audit-{len(cases):02}', group=group,
                                  changes=dict(fatigue=fatigue, pain=pain, sleep=sleep)))
    return cases


def bracket(history, before):
    """Interpolate native action names; disagreement or extrapolation produces no claim."""
    for key in ('pain', 'sleep_pressure'):
        values = [row['before'][key] for row in history]
        if not min(values) <= before[key] <= max(values):
            return None
    by_fatigue = {}
    for row in history:
        by_fatigue.setdefault(row['before']['fatigue'], set()).add(row['actual_action'])
    fatigue = before['fatigue']
    below = [f for f in by_fatigue if f <= fatigue]
    above = [f for f in by_fatigue if f >= fatigue]
    if not below or not above:
        return None
    labels = by_fatigue[max(below)] | by_fatigue[min(above)]
    return next(iter(labels)) if len(labels) == 1 else None


def counts(rows, field):
    rare = 'slow_breath'
    positives = sum(row['actual_action'] == rare for row in rows)
    alarm = 'other' if field == 'incumbent' else rare
    asserted = [row for row in rows if row[field] is not None]
    correct = sum(row[field] == (row['actual_bucket'] if field == 'incumbent'
                                else row['actual_action']) for row in asserted)
    caught = sum(row[field] == alarm and row['actual_action'] == rare for row in rows)
    false_alarms = sum(row[field] == alarm and row['actual_action'] != rare for row in rows)
    per_class = {}
    for action in sorted({row['actual_action'] for row in rows}):
        items = [row for row in rows if row['actual_action'] == action]
        hits = sum(row[field] == (row['actual_bucket'] if field == 'incumbent'
                                  else action) for row in items)
        per_class[action] = hits / len(items)
    return dict(n=len(rows), asserted=len(asserted), abstained=len(rows)-len(asserted),
                correct_assertions=correct, rare_actual=positives, rare_caught=caught,
                rare_false_alarms=false_alarms, rare_recall=caught/positives if positives else None,
                class_recalls=per_class, macro_recall=sum(per_class.values())/len(per_class))


def run(output):
    # The legacy fixture writes generated defaults alongside its runtime. Only its verified
    # temporary copy is imported. All body sessions and their locks also stay in temp space.
    with tempfile.TemporaryDirectory(prefix='nasuraya-breath-audit-') as tmp:
        root = Path(tmp)
        for name in verified_sources():
            target = root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE/name, target)
        sys.path.insert(0, str(root))
        from reflection_cycle import digest
        from synthetic_fixture import prepare_defaults, synthetic_origin
        from . import continuous_self_knowledge as continuous
        from .continuous_self_eval import make_body, start_session
        from .experience import metrics
        from .host import executed_body
        from .self_knowledge import _bucket
        from .self_knowledge_eval import _append, _write

        cfg = ROOT/'docs/evidence/continuous-self-knowledge-v02/selected-config.json'
        config = json.loads(cfg.read_text())
        cases = panel()
        output.mkdir(parents=True, exist_ok=False)
        protocol = dict(cases=cases, duration_s=.1, preferred_action='walk',
                        incumbent_config=config, procedure='two-bracket exact agreement; no extrapolation in pain or sleep',
                        score='supported other is counted as an alarm for incumbent; abstention counts as missed recall')
        _write(output/'protocol.json', protocol)
        prepare_defaults()
        origin = synthetic_origin()
        history, results = [], []
        for case in cases:
            ident, group = case['id'], case['group']
            body = make_body(origin, case['changes'])
            with start_session(root/f'{ident}.sqlite', ident, body, 1) as loop:
                snapshot = loop.observe()
                before = metrics(snapshot)
                feedback = continuous.native_feedback(loop, snapshot, .1)['state']
                if group != 'fit':
                    incumbent = continuous.forecast_action(history, before=before, feedback=feedback,
                        preferred='walk', duration_s=.1, config=config)
                    prediction = dict(id=ident, group=group, before=before,
                        checkpoint=snapshot['checkpoint_sha256'], fit_digest=digest(history),
                        incumbent=incumbent['predicted_action'], incumbent_status=incumbent['status'],
                        incumbent_distribution=incumbent['distribution'], exact=bracket(history, before))
                    _append(output/'forecasts.jsonl', prediction)
                receipt = loop.step(decision_id=ident, duration_s=.1, preferred_action='walk')
                record = loop.engine.get(ident)
                if (not executed_body(record) or record['request']['evidence'][0]['source_sha256']
                        != snapshot['checkpoint_sha256'] or receipt['actual_action']
                        != record['actual_outcome']['selected_action']):
                    raise ValueError('unverified native receipt '+ident)
                actual = receipt['actual_action']
                row = dict(id=ident, group=group, checkpoint=snapshot['checkpoint_sha256'],
                           actual_action=actual, native_record_sha256=digest(record))
                _append(output/'receipts.jsonl', row)
                if group == 'fit':
                    history.append(dict(id=ident, before=before, feedback=feedback, preferred='walk',
                        duration_s=.1, actual_action=actual, kind='observed_software_outcome',
                        source='native-decision://'+ident+'/'+row['native_record_sha256']))
                else:
                    results.append(dict(prediction, actual_action=actual, actual_bucket=_bucket(actual)))
        _write(output/'fit.json', history)
        if len({r['id'] for r in history + results}) != len(cases):
            raise ValueError('duplicate native case')
        if any(row['fit_digest'] != digest(history) for row in results):
            raise ValueError('a forecast used a different fit')
        summary = dict(schema='nasuraya-rare-breath-audit/1', protocol_sha256=digest(protocol),
            fit_count=len(history), held_out_count=len(results), native_cycles=len(cases),
            model_api_calls=0, scope='one warm synthetic origin, single-step walks; enriched, non-IID panels')
        for group in ('interpolation', 'stress'):
            data = [row for row in results if row['group'] == group]
            summary[group] = dict(actual=dict(Counter(row['actual_action'] for row in data)),
                                  incumbent_bucket=counts(data, 'incumbent'), exact=counts(data, 'exact'))
        _write(output/'summary.json', summary)
        print(json.dumps(summary, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    run(parser.parse_args().output_dir.resolve())
