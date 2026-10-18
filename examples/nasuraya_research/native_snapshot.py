"""Read-only snapshot extracted from the stacked self-model monitor.

Imports of the existing native runtime stay lazy. The caller initializes its
own body; this module never creates fixtures, stores, controllers or actions.
The observation schema and validation match monitor.snapshot at d219885.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys


def snapshot(body):
    from unified_body_v2 import UnifiedBody
    from persistent_embodiment_v1 import digest
    from audit_self_model import assess

    checkpoint=body.checkpoint()
    UnifiedBody.restore(checkpoint)  # validate clocks, sources and native journal
    audit=assess(body)
    cls=type(body.owner.physical)
    module=Path(sys.modules[cls.__module__].__file__)
    result=dict(native_sha=checkpoint['sha256'],revision=body.revision,
        time_s=body.owner.physical.state.time_s,minimum=deepcopy(audit['saved_minimum_state']),
        audit=audit,body_before_digest=digest(dict(native=body.owner.body(),modules=body.modules,affect=body.affect)),
        source_identity=digest(dict(native=checkpoint['payload']['source_fingerprints'],
            controller=cls.__module__+'.'+cls.__qualname__,controller_sha=hashlib.sha256(module.read_bytes()).hexdigest())),
        evidence_kind='source_pinned_software_observation')
    result['observation_sha256']=digest(result)
    return result
