"""Bounded reporting of forecast error; never a decision or permission score.

The constants are pilot engineering assumptions, not numerical Zohraya laws.
No model, network, global memory or cross-session prior is loaded here.
"""
import math

SCHEMA = 'nasuraya-outcome-calibration/1'
MIN_SAMPLES = 2
MAX_SAMPLES = 3
MAX_CORRECTION = .25
SHRINKAGE_SAMPLES = 2


def probability(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            not math.isfinite(value) or not 0 <= value <= 1):
        raise ValueError('forecast confidence must be finite in [0, 1]')
    return float(value)


def forecast(raw_confidence, domain, history):
    """One pass over at most three completed, same-session observations.

    Domain is the preferred action, guard restrictions and duration. Training
    uses *raw* forecast errors, so previous corrections aren't counted twice.
    Insufficient evidence leaves the caller-declared prior unchanged.
    """
    raw = probability(raw_confidence)
    if len(history) > MAX_SAMPLES:
        raise ValueError('calibration history exceeds finite pilot capacity')
    samples = []
    for row in history:
        if row['domain'] != domain:
            continue
        if type(row['outcome']) is not bool:
            raise ValueError('only resolved binary native outcomes may train calibration')
        samples.append(probability(row['raw_confidence']) - int(row['outcome']))
    # Shrink the mean residual toward no correction: two successes must not
    # promote an interior declared prior to certainty. This is a pilot tuning
    # assumption, not a statistical confidence interval or empirical guarantee.
    bias = sum(samples) / (len(samples) + SHRINKAGE_SAMPLES) if len(samples) >= MIN_SAMPLES else 0.
    correction = max(-MAX_CORRECTION, min(MAX_CORRECTION, bias))
    return dict(schema=SCHEMA, target='preferred_action_executed_by_native_body',
                domain=domain, raw_confidence=raw,
                calibrated_confidence=max(0., min(1., raw - correction)),
                prior_kind='caller_declared_not_empirically_established',
                samples=len(samples), minimum_samples=MIN_SAMPLES,
                shrinkage_samples=SHRINKAGE_SAMPLES,
                correction=correction, max_correction=MAX_CORRECTION,
                correction_active=len(samples) >= MIN_SAMPLES,
                empirical_validation=False,
                outcome=None, outcome_source=None,
                role='report_only_no_decision_or_authority_writeback')


def resolve(prediction, *, outcome, outcome_source):
    if type(outcome) is not bool or not isinstance(outcome_source, str) or not outcome_source:
        raise ValueError('resolved native outcome and source required')
    return dict(prediction, outcome=outcome, outcome_source=outcome_source,
                raw_brier=(prediction['raw_confidence'] - int(outcome)) ** 2,
                calibrated_brier=(prediction['calibrated_confidence'] - int(outcome)) ** 2)
