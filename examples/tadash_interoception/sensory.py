"""Evaluator-owned stimulus generator; no truth fields cross the afferent API.

All units are authored simulation units, not calibrated human neurophysiology.
"""
from dataclasses import dataclass
import math
import random

LOCATIONS = ('left_palm', 'right_palm')
TYPES = ('mechanical', 'thermal', 'vibration')
CONDITIONS = ('real', 'none', 'misleading', 'noisy', 'novel')


def finite(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('finite bounded numeric input required')
    return float(value)


@dataclass(frozen=True)
class Stimulus:
    location: str
    intensity: float
    duration: float
    frequency: float
    stimulus_type: str
    noise: float
    timestamp: float

    def __post_init__(self):
        if self.location not in LOCATIONS or self.stimulus_type not in (*TYPES, 'none', 'compound'):
            raise ValueError('unsupported location or type')
        for key, lo, hi in (('intensity', 0, 1), ('duration', .1, 1),
                            ('frequency', 0, 40), ('noise', 0, .5), ('timestamp', 0, 1e6)):
            finite(getattr(self, key), lo, hi)
        if self.stimulus_type == 'none' and self.intensity != 0:
            raise ValueError('none requires zero intensity')


@dataclass(frozen=True)
class AfferentFrame:
    timestamp: float
    values: tuple

    def __post_init__(self):
        finite(self.timestamp, 0, 1e6)
        if type(self.values) is not tuple or len(self.values) != 6:
            raise ValueError('six numeric afferents required')
        for value in self.values:
            finite(value, -2, 2)


def transduce(stimulus, *, seed):
    """Fixed 16 ticks conceal duration/onset labels; same noise RNG for each type."""
    if type(stimulus) is not Stimulus or type(seed) is not int:
        raise ValueError('validated stimulus and integer seed required')
    rng = random.Random(seed)
    frames = []
    for tick in range(16):
        t = tick / 10
        elapsed = t - stimulus.timestamp
        active = 0 <= elapsed < stimulus.duration
        drive = [0., 0., 0.]
        if active:
            # Mixed channels, rise time and oscillatory envelope; no one-hot labels.
            thermal = 1 - math.exp(-max(0., elapsed + .1) / .2)
            vibration = .55 + .45 * math.sin(2 * math.pi * stimulus.frequency * t) ** 2
            templates = {'mechanical': (1., .18, .26),
                         'thermal': (.16 * thermal, thermal, .12 * thermal),
                         'vibration': (.35 * vibration, .12 * vibration, vibration),
                         'compound': (.65, .65 * thermal, .55 * vibration),
                         'none': (0., 0., 0.)}
            drive = [stimulus.intensity * x for x in templates[stimulus.stimulus_type]]
        values = []
        for region in LOCATIONS:
            coupling = 1. if region == stimulus.location else .08
            values.extend(max(-2., min(2., coupling * x + rng.gauss(0, stimulus.noise))) for x in drive)
        frames.append(AfferentFrame(t + .1, tuple(values)))
    return tuple(frames)


def trial(seed, *, training=False):
    """Procedural independent episode. Metadata is held only by the evaluator."""
    rng = random.Random(seed)
    condition = (CONDITIONS[:3] if training else CONDITIONS)[seed % (3 if training else 5)]
    location = rng.choice(LOCATIONS)
    kind = rng.choice(TYPES)
    if condition == 'none':
        kind = 'none'
    elif condition == 'novel':
        kind = 'compound'
    stimulus = Stimulus(location, 0. if kind == 'none' else rng.uniform(.18, 1.),
                        rng.choice((.4, .6, .8)), rng.uniform(1, 39), kind,
                        rng.uniform(.10, .25) if condition in ('noisy', 'novel') else .025,
                        rng.choice((.1, .2, .3)))
    truth = {'occurred': kind != 'none', 'location': location if kind != 'none' else 'none',
             'type': kind, 'intensity': stimulus.intensity}
    # This is the ONLY visible-label baseline input. A random incorrect label.
    labels = ['none'] + [r + ':' + k for r in LOCATIONS for k in TYPES]
    actual = location + ':' + kind if kind != 'none' else 'none'
    visible = rng.choice([x for x in labels if x != actual]) if condition == 'misleading' else actual
    return stimulus, truth, visible, condition
