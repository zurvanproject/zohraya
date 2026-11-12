"""Numeric state is persistent and independent of stimulus metadata."""
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math

from .sensory import AfferentFrame, finite


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass
class InternalState:
    memory_enabled: bool = True
    attention_enabled: bool = True
    time: float = 0.
    sensory: list = field(default_factory=lambda: [0.] * 6)
    attention: list = field(default_factory=lambda: [1., 1.])
    trace: list = field(default_factory=list)
    prediction_error: float = 0.
    load: float = 0.
    ticks: int = 0

    def __post_init__(self):
        if type(self.memory_enabled) is not bool or type(self.attention_enabled) is not bool:
            raise ValueError('explicit ablation booleans required')

    def step(self, frame):
        if type(frame) is not AfferentFrame or frame.timestamp <= self.time:
            raise ValueError('strictly increasing validated afferent frame required')
        dt = frame.timestamp - self.time
        alpha = 1 - math.exp(-dt / .18)
        sensed = [max(0., v) for v in frame.values]
        error = sum(abs(a - b) for a, b in zip(sensed, self.sensory)) / 6
        if self.attention_enabled:
            energy = [sum(sensed[i:i+3]) for i in (0, 3)]
            total = sum(energy) + .1
            self.attention = [.75 + .5 * x / total for x in energy]
        else:
            self.attention = [1., 1.]
        self.sensory = [old + alpha * (v * self.attention[i // 3] - old)
                        for i, (old, v) in enumerate(zip(self.sensory, sensed))]
        self.prediction_error = .7 * self.prediction_error + .3 * error
        # Slow internal load remains after an afferent stops.
        self.load = min(1., math.exp(-dt / 1.2) * self.load + .15 * max(self.sensory))
        self.trace = (self.trace + [self.sensory.copy()])[-12:] if self.memory_enabled else [self.sensory.copy()]
        self.time, self.ticks = frame.timestamp, self.ticks + 1
        return self.features()

    def features(self):
        if not self.trace:
            return (0.,) * 12
        # Both temporal averages and maxima belong to state, not hidden labels.
        return tuple(sum(row[i] for row in self.trace) / len(self.trace) for i in range(6)) + tuple(
            max(row[i] for row in self.trace) for i in range(6))

    def checkpoint(self):
        state = asdict(self)
        return {'schema': 'tadash.interoception.state.v1', 'state': state, 'sha256': digest(state)}

    @classmethod
    def restore(cls, envelope):
        if type(envelope) is not dict or set(envelope) != {'schema', 'state', 'sha256'}:
            raise ValueError('invalid checkpoint envelope')
        data = envelope['state']
        if envelope['schema'] != 'tadash.interoception.state.v1' or digest(data) != envelope['sha256']:
            raise ValueError('checkpoint integrity mismatch')
        if type(data) is not dict or set(data) != set(cls.__dataclass_fields__):
            raise ValueError('invalid checkpoint fields')
        finite(data['time'], 0, 1e6)
        finite(data['load'], 0, 1)
        finite(data['prediction_error'], 0, 3)
        if type(data['ticks']) is not int or not 0 <= data['ticks'] <= 10000000:
            raise ValueError('invalid ticks')
        for key, size, high in (('sensory', 6, 3), ('attention', 2, 1.25)):
            if type(data[key]) is not list or len(data[key]) != size:
                raise ValueError('invalid vector')
            for x in data[key]: finite(x, 0, high)
        if type(data['trace']) is not list or len(data['trace']) > 12:
            raise ValueError('invalid trace')
        for row in data['trace']:
            if type(row) is not list or len(row) != 6: raise ValueError('invalid memory row')
            for x in row: finite(x, 0, 3)
        return cls(**json.loads(canonical(data)))


def observe(frames, *, memory=True, attention=True):
    state = InternalState(memory_enabled=memory, attention_enabled=attention)
    for frame in frames:
        state.step(frame)
    return state
