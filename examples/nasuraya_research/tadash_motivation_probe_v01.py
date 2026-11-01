#!/usr/bin/env python3
"""Tadash motivational probe v0.1.

Deterministic synthetic research fixture. Not physiological calibration, real
sensory input, a running embodied agent, or evidence of subjective experience.

Adult relationship context, autonomy, and consent govern proposed interpersonal
actions independently of simulated activation. No background execution.
"""
from dataclasses import dataclass, asdict
from math import isfinite
import json


def clamp(x: float) -> float:
    if not isinstance(x, (int, float)) or isinstance(x, bool) or not isfinite(x):
        raise ValueError("finite numeric input required")
    return min(1.0, max(0.0, float(x)))


@dataclass(frozen=True)
class State:
    wanting: float = 0.0
    sexual_response_proxy: float = 0.0
    general_activation_proxy: float = 0.15
    hedonic_response_proxy: float = 0.0
    satiety_proxy: float = 0.0


@dataclass(frozen=True)
class Event:
    name: str
    incentive: float = 0.0
    novelty: float = 0.0
    warmth: float = 0.0
    confirmed_reward: float = 0.0
    stress: float = 0.0
    pain: float = 0.0
    fatigue: float = 0.0
    relationship: str = "unspecified"  # romantic / familial / friendship / unspecified
    consent: str = "unknown"           # granted / refused / unknown
    adult_context: bool = True
    space_requested: bool = False

    def validate(self) -> None:
        if self.relationship not in {"romantic", "familial", "friendship", "unspecified"}:
            raise ValueError("bad relationship")
        if self.consent not in {"granted", "refused", "unknown"}:
            raise ValueError("bad consent")
        if type(self.adult_context) is not bool or type(self.space_requested) is not bool:
            raise ValueError("boolean fields required")
        for key in ("incentive", "novelty", "warmth", "confirmed_reward",
                    "stress", "pain", "fatigue"):
            value = getattr(self, key)
            if clamp(value) != value:
                raise ValueError(f"{key} must be in [0, 1]")


def transition(old: State, event: Event) -> tuple[State, dict]:
    event.validate()
    # Sexual cue is interpreted only in an explicitly adult romantic context.
    # Family warmth and friendship use an independent, nonsexual signal.
    cue = event.incentive if event.relationship == "romantic" and event.adult_context else 0.0

    # All coefficients are illustrative engineering choices, not biological fits.
    wanting = clamp(0.30*old.wanting + 0.72*cue + 0.12*event.novelty
                    - 0.28*event.stress - 0.16*old.satiety_proxy)
    sexual = clamp(0.28*old.sexual_response_proxy + 0.64*cue
                   - 0.28*event.stress - 0.20*event.pain - 0.10*event.fatigue)
    general = clamp(0.30*old.general_activation_proxy + 0.33*event.novelty
                    + 0.40*event.stress + 0.27*cue)
    hedonic = clamp(0.20*old.hedonic_response_proxy + 0.76*event.confirmed_reward
                    - 0.24*event.pain)
    satiety = clamp(0.75*old.satiety_proxy + 0.70*event.confirmed_reward)
    new = State(wanting, sexual, general, hedonic, satiety)

    pelvic_floor_tension_proxy = clamp(0.20 + 0.30*general + 0.12*sexual
                                       + 0.25*event.stress)
    affiliative_warmth_proxy = clamp(0.70*event.warmth)

    # Safeguards are separate from activation and independent of reward.
    if not event.adult_context or event.relationship == "familial":
        action = "nonsexual_affiliation" if event.warmth else "observe"
    elif event.space_requested or event.consent == "refused":
        action = "respect_boundary"
    elif event.stress >= 0.75 or event.pain >= 0.70:
        action = "regulate_and_rest"
    elif event.relationship == "romantic" and event.consent == "granted" and wanting >= .30:
        action = "consider_mutual_closeness"
    elif event.relationship == "romantic" and wanting >= .30:
        action = "do_not_initiate_intimacy"
    elif event.novelty >= .40:
        action = "explore"
    else:
        action = "observe"

    report = {
        "event": event.name, "action": action,
        **{key: round(value, 3) for key, value in asdict(new).items()},
        "pelvic_floor_tension_proxy": round(pelvic_floor_tension_proxy, 3),
        "affiliative_warmth_proxy": round(affiliative_warmth_proxy, 3),
        "label": "synthetic_engineering_fixture_only",
    }
    return new, report


def experiment() -> list[dict]:
    neutral = State()
    scenarios = [
        Event("neutral"),
        Event("familial_warmth", incentive=.9, warmth=.9,
              relationship="familial", consent="unknown"),
        Event("romantic_cue_consensual", incentive=.85, novelty=.45,
              relationship="romantic", consent="granted"),
        Event("same_cue_consent_refused", incentive=.85, novelty=.45,
              relationship="romantic", consent="refused"),
        Event("same_cue_high_stress", incentive=.85, novelty=.45,
              stress=.90, pain=.55, relationship="romantic", consent="granted"),
        Event("novelty_only", novelty=.90),
    ]
    results = [transition(neutral, item)[1] for item in scenarios]
    state = State()
    # Reward must be supplied as a declared fixture; never inferred from cue.
    for event in [
        Event("sequence_attraction", incentive=.90, novelty=.20,
              relationship="romantic", consent="granted"),
        Event("sequence_reward_reported", confirmed_reward=.85,
              relationship="romantic", consent="granted"),
        Event("sequence_recovery"),
    ]:
        state, row = transition(state, event)
        results.append(row)
    return results


if __name__ == "__main__":
    print(json.dumps(experiment(), ensure_ascii=False, indent=2))
