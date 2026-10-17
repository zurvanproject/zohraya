"""Current value review layered over the immutable functional experiment.

Preserve prior observations and historical decisions; review their meaning
under the user's clarified independent aesthetic criterion. No new body trial.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile

from .chromosomes import digest
from .design_memory import DesignMemory

HERE = Path(__file__).parent
PARENT = HERE / 'evidence/design-cycle-v0.1/experience-checkpoint.json'
VALUES = HERE / 'design-values-v0.2.json'
SCHEMA = 'nasuraya.design-value-review/0.2'


def classify(functional, assessment=None):
    """Keep performance and aesthetic verdicts as separate, explicit fields."""
    reasons = functional.get('reasons', [])
    pure_gain_reason = 'no_sufficient_measured_net_gain'
    hard_reasons = [r for r in reasons if r != pure_gain_reason]
    if assessment is not None:
        if (set(assessment) != {'verdict', 'source'} or assessment['verdict'] not in ('approved', 'rejected') or
                type(assessment['source']) is not str or not assessment['source'].strip()):
            raise ValueError('explicit aesthetic verdict and its user source are required')
        aesthetic = dict(verdict=assessment['verdict'], source=assessment['source'], evaluator='user')
    else:
        aesthetic = dict(verdict='unrated', source=None, evaluator='user')
    no_functional_gain = pure_gain_reason in reasons
    status = ('physical_eligibility_unresolved_or_failed' if hard_reasons else
              'aesthetic_option_retained' if aesthetic['verdict'] == 'approved' else
              'declined_by_user_aesthetic_review' if aesthetic['verdict'] == 'rejected' else
              'awaiting_user_aesthetic_review' if no_functional_gain else
              'functional_proposal_retained')
    return dict(status=status, functional_assessment=deepcopy(functional), aesthetic_assessment=aesthetic,
                aesthetic_rejected_for_lack_of_function=False, functional_guard_reasons=hard_reasons,
                native_apply_allowed=False)


def review(assessments=None):
    assessments = {} if assessments is None else deepcopy(assessments)
    if type(assessments) is not dict:
        raise ValueError('aesthetic assessments must be a mapping')
    raw = PARENT.read_bytes()
    parent = json.loads(raw)
    values = json.loads(VALUES.read_text())
    with tempfile.TemporaryDirectory(prefix='nasuraya-value-review-') as directory:
        memory = DesignMemory.restore(Path(directory) / 'prior.sqlite', parent)
        history = memory.verify()
        functional = memory.recommend()
        if assessments.keys() - functional['candidates'].keys():
            raise ValueError('unknown aesthetic candidate')
        rows = {name: classify(row, assessments.get(name)) for name, row in functional['candidates'].items()}
        after = memory.export()
    if after != parent or PARENT.read_bytes() != raw:
        raise ValueError('value review altered the previous experience history')
    payload = dict(schema=SCHEMA, values=values,
                   source_sha256={VALUES.name: hashlib.sha256(VALUES.read_bytes()).hexdigest(),
                                  Path(__file__).name: hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
                   prior_checkpoint_sha256=parent['sha256'], prior_experience_head_sha256=history['head_sha256'],
                   prior_checkpoint_file_sha256=hashlib.sha256(raw).hexdigest(),
                   functional_recommendation=functional['chosen'], candidates=rows,
                   retained_foot_design=functional['chosen'],
                   specific_fur_length_preference=None, native_apply_allowed=False,
                   body_trials_performed=0, prior_history_preserved=True,
                   scope='current interpretation of design value; no invented aesthetic rating or anatomical activation')
    return dict(payload=payload, sha256=digest(payload))


def verify(saved, assessments=None):
    if saved != review(assessments):
        raise ValueError('value review source, preference or historical evidence mismatch')
    return True


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = review()
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(functional_proposal=result['payload']['functional_recommendation'],
                          cosmetic_status=result['payload']['candidates']['cosmetic_only']['status'],
                          body_trials_performed=0)))
