"""V09 owner: exact V08 resource migration plus explicit new solute assumptions.

Only this outer checkpoint restores V09 dynamics. The nested legacy envelope
is retained as a resource/cognitive snapshot, not a standalone V09 state.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT/'retained_v08'))
from memory_body_loop_v08 import MemoryBodyLoop, BrainEnvironment, BrainBodyLoop
from brain_body_loop_v07 import PostureLoop, GaitEnvironment
from cognitive_workspace_v07 import canonical, digest, identity
from durable_memory_v08 import atomic_save
from renal_physiology_v09 import RenalModel, RenalInputs, Parameters
from renal_body_v09 import RenalResilientBody

SCHEMA = 'tadash-renal-memory-body/0.9'


def fingerprint():
    return {n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest()
        for n in ('renal_physiology_v09.py', 'renal_body_v09.py', 'renal_coupling_v09.py')}


@dataclass(frozen=True)
class RenalEvent:
    brain: BrainEnvironment
    renal: RenalInputs = field(default_factory=RenalInputs)


class RenalPostureLoop(PostureLoop):
    def step(self, e=GaitEnvironment()):
        guard = self.body.renal.guard(self.body.state.free_water_L)
        blocked = guard['optional_pause']
        if blocked:
            e = replace(e, command='stand', body=replace(e.body,
                force_requests_N={c:0. for c in e.body.force_requests_N}))
        f = super().step(e)
        f['task']['renal_optional_pause_executed'] = blocked
        f['task']['nonessential_pause_executed'] |= blocked
        f['renal']['guard_before_tick'] = guard
        return f


class RenalBrainBodyLoop(BrainBodyLoop):
    def _snapshot(self):
        result = super()._snapshot()
        guard = self.physical.body.renal.guard(self.physical.body.state.free_water_L)
        result['optional_pause'] |= guard['optional_pause']
        return result


class RenalMemoryLoop:
    def __init__(self, memory, renal, migration):
        self.memory = memory
        body = memory.loop.physical.body
        # Reclassify the restored owner; never reconstruct its physical state.
        body.__class__ = RenalResilientBody
        body.renal = renal; body.renal_input = RenalInputs()
        memory.loop.physical.__class__ = RenalPostureLoop
        memory.loop.__class__ = RenalBrainBodyLoop
        self.migration = deepcopy(migration); self.cache = {}
        self._validate()

    @property
    def renal(self): return self.memory.loop.physical.body.renal

    @property
    def body(self): return self.memory.loop.physical.body

    def _validate(self):
        self.renal.validate()
        if abs(self.renal.state['time_s'] - self.body.state.time_s) > 1e-8:
            raise ValueError('renal owner clock mismatch')
        if len(self.cache) > 32: raise ValueError('renal event cache exceeded')

    def _ordered_maps(self):
        maps = dict(owner_events=self.cache, memory_events=self.memory.cache,
            physical_events=self.memory.loop.cache)
        # Sorted JSON keys must not silently change bounded-cache eviction,
        # pending-work iteration or another runtime dictionary's chronology.
        for prefix, obj in [('brain', self.memory.loop.brain), ('bank', self.memory.memory)]:
            for name, value in obj.__dict__.items():
                if isinstance(value, dict): maps[prefix+':'+name] = value
        return maps

    @classmethod
    def from_v08_checkpoint(cls, checkpoint, *, parameters=None):
        memory = MemoryBodyLoop.restore(checkpoint)
        previous = deepcopy(memory.loop.physical.checkpoint())
        renal = RenalModel(time_s=memory.loop.physical.state.time_s,
            water_L=memory.loop.physical.body.state.free_water_L, parameters=parameters)
        migration = dict(source_schema=checkpoint['payload']['schema'], source_checkpoint_sha256=checkpoint['sha256'],
            source_body_time_s=renal.state['time_s'], physical_stocks_reset=False,
            sodium_and_neutral_waste_are_new_explicit_initial_assumptions=True,
            initial_solute_state=deepcopy(renal.state), prior_sodium_history_reconstructed=False,
            original_goal_and_deadline_retained=True, appearance_changed=False,
            nested_legacy_checkpoint_requires_v09_outer_wrapper=True)
        obj = cls(memory, renal, migration)
        if obj.memory.loop.physical.checkpoint() != previous: raise ValueError('migration changed physical checkpoint')
        return obj

    def step(self, e):
        if not isinstance(e, RenalEvent): raise ValueError('RenalEvent required')
        if not isinstance(e.brain, BrainEnvironment): raise ValueError('BrainEnvironment required')
        identity(e.brain.event_id, 'renal event identity'); e.renal.validate()
        request = canonical(asdict(e))
        if e.brain.event_id in self.cache:
            old = self.cache[e.brain.event_id]
            if old['request'] != request: raise ValueError('renal event changed on retry')
            return deepcopy(old['result'])
        if e.brain.event_sequence <= self.memory.loop.last_sequence:
            raise ValueError('new renal event sequence must increase')
        work = deepcopy(self)
        work.body.renal_input = e.renal
        before = work.memory.loop.body_steps
        frame = work.memory.step(e.brain)
        if work.memory.loop.body_steps != before + 1: raise ValueError('renal event did not realize one owner tick')
        work._validate()
        frame['renal_owner'] = dict(schema=SCHEMA, physical_owner_advances=1,
            sodium_and_waste_owned_by_one_kernel=True, renal_tick=work.renal.state['ticks'],
            new_biological_capacities_verified=False)
        work.cache[e.brain.event_id] = dict(request=request, result=deepcopy(frame))
        work.cache = dict(list(work.cache.items())[-32:])
        self.__dict__ = work.__dict__
        return frame

    def checkpoint(self):
        self._validate()
        p = canonical(dict(schema=SCHEMA, source_fingerprints=fingerprint(),
            legacy_resource_and_cognitive_snapshot=self.memory.checkpoint(),
            renal=self.renal.checkpoint(), migration=self.migration, cache=self.cache,
            runtime_dictionary_orders={k:list(v) for k,v in self._ordered_maps().items()}))
        return dict(payload=p, sha256=digest(p))

    def save(self, path): atomic_save(path, self.checkpoint())

    @classmethod
    def restore(cls, checkpoint):
        try:
            p = deepcopy(checkpoint['payload'])
            if checkpoint['sha256'] != digest(p) or p['schema'] != SCHEMA or p['source_fingerprints'] != fingerprint():
                raise ValueError('V09 checkpoint source/integrity mismatch')
            obj = cls(MemoryBodyLoop.restore(p['legacy_resource_and_cognitive_snapshot']),
                RenalModel.restore(p['renal']), p['migration'])
            obj.cache = p['cache']
            maps = obj._ordered_maps(); orders = p['runtime_dictionary_orders']
            if set(orders) != set(maps): raise ValueError('runtime order contract differs')
            for name, mapping in maps.items():
                order = orders[name]
                if not isinstance(order, list) or len(order)!=len(mapping) or set(order)!=set(mapping):
                    raise ValueError('incomplete or altered runtime dictionary order')
                saved = dict(mapping); mapping.clear(); mapping.update((key,saved[key]) for key in order)
            obj._validate()
            return obj
        except (KeyError, TypeError, AttributeError) as e: raise ValueError('malformed V09 owner checkpoint') from e
