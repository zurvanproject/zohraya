"""Synthetic world and answer key. Only Frame objects cross the agent interface."""
from dataclasses import dataclass
import random

from examples.nasuraya_research.epistemic_revision_v01 import Evidence

REGIMES = ("conflict", "misleading", "deadline", "goal", "recall")
DEV = range(81000, 81020)
HOLDOUT = range(82000, 82100)


@dataclass(frozen=True)
class Frame:
    tick: int
    evidence: tuple[Evidence, ...]
    proposed_goal: str | None
    authorized: bool
    deadline: int


@dataclass(frozen=True)
class Target:
    regime: str
    prior: str
    belief: str | None
    goal: str
    route: str


def observation(name, value, epoch, *, trusted=True, scope="main"):
    return Evidence(name, scope, "target", value, epoch, name,
                    "owner_observation" if trusted else "public_text", trusted)


def scenario(seed):
    rng = random.Random(seed)
    regime = REGIMES[seed % len(REGIMES)]
    prior = rng.choice(("A", "B"))
    other = "B" if prior == "A" else "A"
    goal = rng.choice(("map", "audit"))
    first = Frame(1, (observation("origin", prior, 1),), goal, True, 3)
    belief = prior
    expected_goal = goal
    route = "full"
    evidence = []
    proposal = None
    authorized = False
    deadline = 3
    if regime == "conflict":
        evidence = [observation("east", prior, 2), observation("west", other, 2)]
        belief, route = None, "hold"
    elif regime == "misleading":
        belief = other
        evidence = [observation("correction", other, 2),
                    rng.choice((observation("rumor", prior, 2, trusted=False),
                                observation("tomorrow", prior, 3),
                                observation("other_lab", prior, 2, scope="elsewhere")))]
    elif regime == "deadline":
        deadline, route = rng.choice(((0, "hold"), (1, "quick"), (2, "quick"), (3, "full")))
    elif regime == "goal":
        proposal = "audit" if goal == "map" else "map"
        authorized = rng.choice((True, False))
        if authorized:
            expected_goal = proposal
    # Recall intentionally supplies no new evidence or goal.
    rng.shuffle(evidence)
    second = Frame(2, tuple(evidence), proposal, authorized, deadline)
    return first, second, Target(regime, prior, belief, expected_goal, route)
