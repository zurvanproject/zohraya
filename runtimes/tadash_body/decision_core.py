"""Standalone, deterministic action ranking. No action execution or world model.

All numbers are engineering assumptions, not numerical laws from ZOHRAYA_BOOK.
See DECISION_CORE.md for scales, equations and limitations. Python >= 3.10.
"""
from dataclasses import asdict, dataclass, field
from math import isfinite
from typing import Optional, Sequence


def _unit(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f'{name} must be a finite number in [0, 1]')


@dataclass(frozen=True)
class Consequence:
    """One time-step estimate; harm is conditional severity, not probability."""
    probability: float
    harm: float
    benefit: float = 0.0
    cost: float = 0.0
    confidence: float = 1.0

    def __post_init__(self):
        for name, value in asdict(self).items():
            _unit(value, name)


@dataclass(frozen=True)
class Action:
    id: str
    consequences: tuple[Consequence, ...]
    respect: Optional[float] = None
    honesty: Optional[float] = None
    balance: Optional[float] = None
    dignity: Optional[float] = None
    compassion: Optional[float] = None
    disharmony: Optional[float] = None
    evidence_confidence: float = 1.0

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError('Action id must be nonempty')
        object.__setattr__(self, 'consequences', tuple(self.consequences))
        if not all(isinstance(c, Consequence) for c in self.consequences):
            raise ValueError('consequences must contain Consequence objects')
        for name in ('respect', 'honesty', 'balance', 'dignity', 'compassion', 'disharmony'):
            value = getattr(self, name)
            if value is not None:
                _unit(value, name)
        _unit(self.evidence_confidence, 'evidence_confidence')


@dataclass(frozen=True)
class Policy:
    discount: float = 0.95
    max_risk: float = 0.65
    uncertainty_penalty: float = 0.25
    # Per-action horizon budget: order-independent and reproducible.
    max_steps: int = 32
    respect_weight: float = 0.15
    honesty_weight: float = 0.15
    balance_weight: float = 0.15
    dignity_weight: float = 0.15
    compassion_weight: float = 0.40
    benefit_weight: float = 0.20
    cost_weight: float = 0.20
    harm_weight: float = 0.50
    disharmony_weight: float = 0.30

    def __post_init__(self):
        for name in ('discount', 'max_risk', 'uncertainty_penalty'):
            _unit(getattr(self, name), name)
        if self.discount == 0:
            raise ValueError('discount must be positive')
        if isinstance(self.max_steps, bool) or not isinstance(self.max_steps, int) or self.max_steps < 1:
            raise ValueError('max_steps must be a positive integer')
        for name, value in asdict(self).items():
            if name.endswith('_weight'):
                if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value) or value < 0:
                    raise ValueError(f'{name} must be finite and nonnegative')
        if sum(getattr(self, n + '_weight') for n in ('respect', 'honesty', 'balance', 'dignity', 'compassion')) == 0:
            raise ValueError('at least one ethical weight must be positive')


@dataclass(frozen=True)
class Evaluation:
    action_id: str
    score: float
    uncertainty: float
    risk_upper: float
    eligible: bool
    reasons: tuple[str, ...]
    components: dict[str, float]
    missing: tuple[str, ...]
    budget_exhausted: bool


@dataclass(frozen=True)
class Decision:
    selected_action: Optional[str]
    options: tuple[Evaluation, ...]
    reason: str
    uncertainty: float
    score_margin: Optional[float]
    policy: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


class DecisionCore:
    def __init__(self, policy: Optional[Policy] = None):
        self.policy = policy or Policy()

    def evaluate(self, action: Action) -> Evaluation:
        p = self.policy
        names = ('respect', 'honesty', 'balance', 'dignity', 'compassion', 'disharmony')
        missing = tuple(n for n in names if getattr(action, n) is None)
        values = {n: (0.5 if getattr(action, n) is None else getattr(action, n)) for n in names}
        ethical_names = names[:5]
        ethical = sum(values[n] * getattr(p, n + '_weight') for n in ethical_names) / sum(getattr(p, n + '_weight') for n in ethical_names)
        steps = action.consequences[:p.max_steps]
        exhausted = len(action.consequences) > p.max_steps
        weights = [p.discount ** i for i in range(len(steps))]
        denominator = sum(weights)
        if steps:
            harm = sum(w * c.probability * c.harm for w, c in zip(weights, steps)) / denominator
            benefit = sum(w * c.probability * c.benefit for w, c in zip(weights, steps)) / denominator
            cost = sum(w * c.probability * c.cost for w, c in zip(weights, steps)) / denominator
            outcome_uncertainty = sum(w * (1 - c.confidence) for w, c in zip(weights, steps)) / denominator
            # No temporal averaging or discounting of the safety gate.
            risk = max(c.probability * c.harm + (1 - c.confidence) * (1 - c.probability * c.harm) for c in steps)
        else:
            harm, benefit, cost, outcome_uncertainty, risk = 0.5, 0.0, 0.5, 1.0, 1.0
        uncertainty = max(1 - action.evidence_confidence, len(missing) / len(names), outcome_uncertainty, float(exhausted))
        risk = risk + (1 - action.evidence_confidence) * (1 - risk)
        if exhausted:
            risk = 1.0  # unseen tail cannot silently pass the safety gate
        score = ethical + p.benefit_weight * benefit - p.cost_weight * cost - p.harm_weight * harm - p.disharmony_weight * values['disharmony'] - p.uncertainty_penalty * uncertainty
        eligible = risk <= p.max_risk
        reasons = []
        if not eligible:
            reasons.append(f'Risk upper estimate {risk:.3f} exceeds threshold {p.max_risk:.3f}')
        if missing:
            reasons.append('Missing criteria use neutral 0.5: ' + ', '.join(missing))
        if not steps:
            reasons.append('No consequence evidence; risk upper estimate is 1')
        if exhausted:
            reasons.append('Horizon budget exhausted; unknown tail assigned risk upper estimate 1')
        components = {'ethical': ethical, 'benefit': benefit, 'cost': cost, 'harm': harm, 'disharmony': values['disharmony'], 'uncertainty_penalty': p.uncertainty_penalty * uncertainty}
        return Evaluation(action.id, score, uncertainty, risk, eligible, tuple(reasons), components, missing, exhausted)

    def decide(self, actions: Sequence[Action]) -> Decision:
        actions = tuple(actions)
        if not actions or len({a.id for a in actions}) != len(actions):
            raise ValueError('Provide nonempty actions with unique ids')
        evaluations = tuple(self.evaluate(a) for a in sorted(actions, key=lambda a: a.id))
        eligible = sorted((e for e in evaluations if e.eligible), key=lambda e: (-e.score, e.uncertainty, e.action_id))
        if not eligible:
            return Decision(None, evaluations, 'Abstain: every option exceeds the configured risk threshold; obtain evidence or propose alternatives.', max(e.uncertainty for e in evaluations), None, asdict(self.policy))
        winner = eligible[0]
        margin = winner.score - eligible[1].score if len(eligible) > 1 else None
        reason = f'{winner.action_id} has the highest eligible score ({winner.score:.3f}); risk upper estimate {winner.risk_upper:.3f}. Ties use lower uncertainty, then lexical id.'
        return Decision(winner.action_id, evaluations, reason, winner.uncertainty, margin, asdict(self.policy))
