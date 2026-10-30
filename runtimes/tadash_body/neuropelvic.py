"""TADASH Neuro-Pelvic v0.2: an explicit, bounded synthetic regulation cycle.

All quantities and time constants are authored simulator parameters, not human
physiology, measured pleasure, or evidence of subjective experience. Chakra
channels are symbolic feature labels. This module is not a full-body adapter.
"""
from dataclasses import asdict, dataclass
from math import ceil, exp, isfinite, pi, sin
from numbers import Real
import json

CHAKRAS = ('root', 'sacral', 'solar_plexus', 'heart', 'throat', 'brow', 'crown')
NORMALIZED_FIELDS = (
    'arousal', 'pelvic_tone', 'genital_perfusion', 'pudendal_drive',
    'autonomic_drive', 'fatigue', 'tail_stability', 'breath_rate',
    'heart_rate', 'sacral_signal', 'resonance', 'settling',
)


def finite_number(value, name):
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
        raise ValueError(f'{name} must be a finite real number')
    return float(value)


def clamp(value):
    return max(0., min(1., finite_number(value, 'normalized input')))


def relax(current, target, dt, tau):
    return clamp(target + (current - target) * exp(-dt / tau))


@dataclass
class State:
    time: float = 0.
    phase: str = 'baseline'
    arousal: float = 0.
    pelvic_tone: float = .30
    genital_perfusion: float = .25
    pudendal_drive: float = .10
    autonomic_drive: float = .20
    fatigue: float = 0.
    tail_stability: float = .80
    breath_rate: float = .30
    heart_rate: float = .30
    chakra: tuple = (.30,) * 7
    sacral_signal: float = 0.
    resonance: float = 0.
    settling: float = 0.


class NeuroPelvic:
    """An intentionally started cycle with state-dependent peak and restoration.

    Call start_cycle() once, then step()/run(). Music alone never starts a
    cycle. After a peak or interruption, another explicit start is required.
    breath_cue/attention are synthetic settling gains, not breathing advice.
    """
    PEAK_THRESHOLD = .72
    PEAK_HOLD_SECONDS = 1.2
    PEAK_SECONDS = 1.6
    MAX_RISING_SECONDS = 20.
    MIN_RECOVERY_SECONDS = 6.
    REST_TOLERANCE = .015
    INTERNAL_DT = .02

    def __init__(self):
        self.state = State()
        self.peak_count = 0
        self.events = []
        self._phase_elapsed = 0.
        self._above_threshold = 0.

    def _transition(self, phase, reason):
        previous = self.state.phase
        if previous == phase:
            return
        self.state.phase = phase
        self._phase_elapsed = 0.
        self._above_threshold = 0.
        self.events.append({
            'time': round(self.state.time, 6), 'from': previous, 'to': phase,
            'reason': reason, 'arousal': self.state.arousal,
        })

    def baseline_residual(self):
        """Largest deviation from rest, excluding the active settling cue."""
        baseline = State()
        values = [abs(getattr(self.state, key) - getattr(baseline, key))
                  for key in NORMALIZED_FIELDS if key != 'settling']
        values.extend(abs(value - .30) for value in self.state.chakra)
        return max(values)

    def start_cycle(self):
        if self.state.phase != 'baseline' or self.baseline_residual() > self.REST_TOLERANCE:
            return False
        self._transition('rising', 'explicit_start')
        return True

    @staticmethod
    def _validate_dt(dt):
        dt = finite_number(dt, 'dt')
        if not 0 < dt <= 1:
            raise ValueError('dt must be in (0, 1]')
        return dt

    def step(self, dt=.1, rhythm=0., intensity=.5, *, breath_cue=0.,
             attention=0., pain=0., safe=True, balance=1., stop=False):
        dt = self._validate_dt(dt)
        # Validate every input before changing any state.
        rhythm, intensity, breath_cue, attention, pain, balance = map(
            clamp, (rhythm, intensity, breath_cue, attention, pain, balance))
        if not isinstance(safe, bool) or not isinstance(stop, bool):
            raise ValueError('safe and stop must be booleans')
        reason = ('stop' if stop else 'unsafe' if not safe else
                  'pain' if pain > .05 else 'balance' if balance < .50 else None)
        if reason and self.state.phase in ('rising', 'peak'):
            self._transition('release', reason)
        # A bounded internal integration step limits coarse-step artifacts.
        count = max(1, ceil(dt / self.INTERNAL_DT - 1e-12))
        for _ in range(count):
            self._advance(dt / count, rhythm, intensity, breath_cue, attention,
                          blocked=reason is not None)
        return asdict(self.state)

    def _advance(self, dt, rhythm, intensity, breath_cue, attention, blocked):
        s = self.state
        s.time = round(s.time + dt, 10)
        self._phase_elapsed += dt
        if s.phase in ('rising', 'peak') and intensity <= .05:
            self._transition('release', 'input_withdrawn')
        active = s.phase in ('rising', 'peak') and not blocked
        target = clamp(.88 * intensity + .12 * rhythm) if active else 0.
        restorative = s.phase in ('release', 'recovery')
        settling_target = (.70 * breath_cue + .30 * attention) if restorative else 0.
        s.settling = relax(s.settling, settling_target, dt, .7)
        tau = 1.8 if active else 1.8 / (1. + .6 * breath_cue + .3 * attention)
        s.arousal = relax(s.arousal, target, dt, tau)
        s.sacral_signal = clamp(.78 * s.arousal) if active else 0.
        s.resonance = clamp(.65 * s.sacral_signal * (1. - .5 * s.fatigue)) if active else 0.
        pulse = .075 * sin(2 * pi * 2. * self._phase_elapsed) * s.arousal if s.phase == 'peak' else 0.
        s.pelvic_tone = relax(s.pelvic_tone, clamp(.30 + .48 * s.arousal + pulse), dt, .45)
        s.genital_perfusion = relax(s.genital_perfusion, .25 + .50 * s.arousal, dt, .8)
        s.pudendal_drive = relax(s.pudendal_drive, .10 + .70 * s.sacral_signal, dt, .35)
        s.autonomic_drive = relax(s.autonomic_drive, .20 + .55 * s.arousal, dt, .7)
        s.fatigue = (clamp(s.fatigue + .045 * dt) if s.phase == 'peak'
                     else relax(s.fatigue, 0., dt, 8.))
        s.tail_stability = relax(s.tail_stability,
            clamp(.80 - .15 * (s.pelvic_tone - .30) - .06 * s.fatigue), dt, .7)
        s.breath_rate = relax(s.breath_rate, .30 + .45 * s.arousal, dt, .8)
        s.heart_rate = relax(s.heart_rate, .30 + .38 * s.arousal, dt, 1.)
        symbolic = (s.sacral_signal * .08, s.sacral_signal * .35,
                    s.resonance * .15, s.resonance * .10,
                    s.resonance * .08 * rhythm, s.resonance * .06 * attention,
                    s.resonance * .04)
        s.chakra = tuple(relax(old, .30 + feature, dt, 1.5)
                         for old, feature in zip(s.chakra, symbolic))

        if s.phase == 'rising':
            self._above_threshold = (self._above_threshold + dt
                                     if s.arousal >= self.PEAK_THRESHOLD else 0.)
            if self._above_threshold + 1e-9 >= self.PEAK_HOLD_SECONDS:
                self.peak_count += 1
                self._transition('peak', 'threshold_held')
            elif self._phase_elapsed + 1e-9 >= self.MAX_RISING_SECONDS:
                self._transition('release', 'rising_timeout')
        elif s.phase == 'peak' and self._phase_elapsed + 1e-9 >= self.PEAK_SECONDS:
            self._transition('release', 'peak_complete')
            s.sacral_signal = s.resonance = 0.
        elif s.phase == 'release' and self._phase_elapsed >= 1.5 and s.arousal <= .12:
            self._transition('recovery', 'arousal_settled')
        elif (s.phase == 'recovery' and
              self._phase_elapsed + 1e-9 >= self.MIN_RECOVERY_SECONDS and
              self.baseline_residual() <= self.REST_TOLERANCE):
            self._transition('baseline', 'restored')
            # Snap only within the declared rest tolerance.
            self.state = State(time=s.time)

    def run(self, seconds=60., dt=.1, rhythm=.5, intensity=.5, **inputs):
        seconds = finite_number(seconds, 'seconds')
        dt = self._validate_dt(dt)
        if seconds < 0:
            raise ValueError('seconds must be nonnegative')
        # Preflight input validation even for an empty run, without touching self.
        NeuroPelvic().step(dt, rhythm, intensity, **inputs)
        steps = int(seconds / dt)
        trace = [self.step(dt, rhythm, intensity, **inputs) for _ in range(steps)]
        remainder = seconds - steps * dt
        if remainder > 1e-9:
            trace.append(self.step(remainder, rhythm, intensity, **inputs))
        return trace


if __name__ == '__main__':
    model = NeuroPelvic()
    model.start_cycle()
    trace = model.run(60., intensity=.95, rhythm=.70, breath_cue=.8, attention=.7)
    print(json.dumps({'model': 'TADASH Neuro-Pelvic v0.2',
                      'scope': 'standalone synthetic module',
                      'samples': len(trace), 'peak_count': model.peak_count,
                      'events': model.events, 'end': trace[-1]}, indent=2))
