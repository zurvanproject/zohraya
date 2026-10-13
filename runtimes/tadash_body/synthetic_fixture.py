"""Deterministic fixtures constructed from defaults, never from saved user state."""
from datetime import datetime, timezone
from pathlib import Path
import sys

from unified_body_v2 import ROOT, UnifiedBody, PersistentEmbodiment
from memory_body_loop_v08 import MemoryBodyLoop
from renal_coupling_v09 import RenalMemoryLoop
from neural_circuit import toy_circuit
import nasuraya_affective_layer_v01 as affect


def prepare_defaults():
    # These legacy filenames hold generated test defaults, not trained/user data.
    directory = ROOT / 'retained_extensions'
    toy_circuit(learned_weight_ns=12.0).save(directory / 'trained_circuit.json')
    affect.save(affect.initial_state(), directory / 'initial_affect.json')


def synthetic_origin():
    memory = MemoryBodyLoop(context='synthetic-test', epoch='synthetic-v1')
    renal = RenalMemoryLoop.from_v08_checkpoint(memory.checkpoint())
    owner = PersistentEmbodiment.bootstrap(
        renal.checkpoint(), datetime(2026, 1, 1, tzinfo=timezone.utc))
    # A short declared warm-up permits positive timestamps for expired samples.
    owner.cycle(event_id='synthetic-warm-up',
                at_utc='2026-01-01T00:00:07+00:00', duration_s=7.0,
                requested='observe', external={})
    return owner.checkpoint()


def synthetic_body():
    return UnifiedBody.migrate(synthetic_origin())


if __name__ == '__main__':
    prepare_defaults()
