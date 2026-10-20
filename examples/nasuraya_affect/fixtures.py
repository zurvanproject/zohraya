"""Explicit synthetic inputs; no scores inferred from real people or transcripts."""
from .engine import CHECKS, TENDENCIES


def event(identifier='e1', *, context='simulation', topic='learning', cues=None,
          elapsed_hours=0., summary='Constructed affective scenario', **checks):
    appraisal = dict.fromkeys(CHECKS, 0.)
    appraisal.update(relevance=1., certainty=1., controllability=.5)
    appraisal.update(checks)
    return dict(id=identifier, context=context, topic=topic,
                cues=cues or ['experiment'], elapsed_hours=elapsed_hours,
                source=dict(kind='authored', locator='fixture://' + identifier),
                summary=summary, appraisal=appraisal)


def option(identifier, *, tendency=None, harm=0., cost=0., confidence=1.):
    return dict(action=dict(id=identifier,
                           consequences=[dict(probability=1., harm=harm, cost=cost)],
                           respect=1., honesty=1., balance=1., dignity=1.,
                           compassion=1., disharmony=0., evidence_confidence=confidence),
                tendencies={k: float(k == tendency) for k in TENDENCIES})


def options(tendency='repair'):
    return [option('a_continue'), option('b_adapt', tendency=tendency, cost=.01)]
