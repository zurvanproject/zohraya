"""Read-only, post-hoc sensitivity analysis; never creates training labels.

The preregistered primary score conditions on completed native execution.
This secondary interpretation also counts a known freshness-blocked attempt
as failure to execute the preferred action. That is an explicitly imputed
evaluation label, not an outcome receipt or a production learning sample.
"""
import argparse
import json
from pathlib import Path

from .transfer import read_sealed


def analyze(directory):
    result = read_sealed(Path(directory)/'results.json')
    pairs = []
    imputed = []
    for row in result['cases']:
        if row['scored']:
            prediction = row['prediction']
            pairs.append((prediction['raw_brier'], prediction['calibrated_brier']))
        elif (row['status'] == 'blocked' and row['reason'] == 'stale body observation'
              and row['native_cycles'] == 0 and 'prediction' in row):
            p = row['prediction']
            pairs.append((p['raw_confidence']**2, p['calibrated_confidence']**2))
            imputed.append(row['case']['id'])
    if not pairs:
        raise ValueError('no scoreable forecasts')
    return dict(schema='nasuraya-transfer-posthoc-sensitivity/1',
        analysis_timing='added after the primary protocol completed; exploratory',
        interpretation='guard-blocked attempt counts as nonexecution of preferred action',
        native_labelled_cases=result['summary']['scored_forecasts'],
        imputed_zero_cases=imputed, total_scored=len(pairs),
        raw_mean_brier=sum(x for x,y in pairs)/len(pairs),
        frozen_transfer_mean_brier=sum(y for x,y in pairs)/len(pairs),
        original_primary_result_modified=False, production_labels_written=0,
        empirical_validation=False, general_improvement_demonstrated=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    print(json.dumps(analyze(parser.parse_args().directory), ensure_ascii=False, indent=2))
