"""Synthetic TADASH neuro-pelvic and seven-symbolic-center control model.

The normalized values are simulation variables, not measured physiology
or evidence of subjective experience. No biological chakras are asserted.
"""
from dataclasses import dataclass, asdict
from math import sin, pi

CHAKRAS = ("root", "sacral", "solar_plexus", "heart", "throat", "brow", "crown")

def clamp(v):
    return max(0.0, min(1.0, float(v)))

@dataclass
class State:
    time: float = 0.0
    phase: str = "baseline"
    arousal: float = 0.0
    pelvic_tone: float = 0.30
    genital_perfusion: float = 0.25
    pudendal_drive: float = 0.10
    autonomic_drive: float = 0.20
    fatigue: float = 0.0
    tail_stability: float = 0.80
    breath_rate: float = 0.30
    heart_rate: float = 0.30
    chakra: tuple = (0.30,) * 7

class NeuroPelvic:
    def __init__(self):
        self.state = State()

    def step(self, dt=0.1, rhythm=0.0, intensity=0.5):
        if not (0 < dt <= 1):
            raise ValueError("dt must be in (0,1]")
        s = self.state
        rhythm, intensity = clamp(rhythm), clamp(intensity)
        t = s.time + dt
        cycle = t % 20
        if cycle < 3:
            phase, drive = "baseline", 0.08
        elif cycle < 9:
            phase, drive = "rising", 0.35 + 0.075 * (cycle - 3)
        elif cycle < 11:
            phase, drive = "peak", 0.95
        elif cycle < 15:
            phase, drive = "release", 0.65 - 0.13 * (cycle - 11)
        else:
            phase, drive = "recovery", 0.07
        target = (clamp(drive * intensity + 0.16 * rhythm)
                  if phase not in ("baseline", "recovery") else drive)
        a = clamp(s.arousal + (target - s.arousal) * min(1., dt * 2))
        p = clamp(0.25 + 0.62 * a +
                  (0.10 * sin(2 * pi * 2.5 * t) * a if phase == "peak" else 0))
        fatigue = clamp(s.fatigue + dt * (0.065 if phase == "peak" else -0.025))
        tail = clamp(0.87 - 0.20 * p - 0.12 * fatigue)
        aut = clamp(0.15 + 0.68 * a)
        channels = (0.27 + 0.30 * (1-tail), 0.20 + 0.70*a,
                    0.22 + 0.40*aut, 0.25 + 0.28*(1-fatigue),
                    0.20 + 0.20*rhythm, 0.21 + 0.25*(1-fatigue),
                    0.18 + 0.15*(1-a))
        self.state = State(round(t, 5), phase, a, p,
                           clamp(0.20+0.65*a), clamp(0.10+0.70*a),
                           aut, fatigue, tail, clamp(0.25+0.52*a),
                           clamp(0.30+0.43*a),
                           tuple(clamp(x) for x in channels))
        return asdict(self.state)

    def run(self, seconds=60.0, dt=0.1, rhythm=0.5):
        return [self.step(dt=dt, rhythm=rhythm)
                for _ in range(round(seconds/dt))]
