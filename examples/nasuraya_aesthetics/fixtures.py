"""Explicit synthetic declarations for tests and demonstrations; no measured images."""
from .appraisal import reference


def observation(*, subject='self', beauty=.9, confidence=1., image_sha256=None):
    return dict(id='fixture', image_sha256=image_sha256 or reference()['sha256'],
                subject=subject, source='synthetic_fixture', source_ref='fixture://visual-contract',
                ratings={} if beauty is None else {'beauty': dict(value=beauty, confidence=confidence,
                    kind='synthetic_fixture', source_ref='fixture://beauty-rating')})


def similarity(value, confidence=1.):
    return dict(value=value, confidence=confidence, kind='synthetic_fixture',
                source_ref='fixture://identity-rating', reference_sha256=reference()['sha256'])
