"""Small, testable cognitive MECHANISM PROTOTYPES, not consciousness.

These stdlib-only components never access an LLM, network, the true Tadash
controller, operator state, finance ledger, private body data or actuators.
They illustrate 14 theory-derived targets in an isolated numerical sandbox.
Passing their unit tests does not establish that Tadash implements a theory.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import math


def scalar(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("finite scalar in [0,1] required")
    return float(value)


@dataclass
class RecurrentBinder:
    recurrent: bool = True
    trace: float = 0.0

    def observe(self, visual, audio):
        visual, audio = scalar(visual), scalar(audio)
        # Explicit cross-modal congruence; not a claim about rich perception.
        binding = 1.0 - abs(visual - audio)
        combined = 0.7 * (visual + audio) / 2 + 0.3 * binding
        result = 0.65 * combined + (0.35 * self.trace if self.recurrent else 0.0)
        self.trace = result if self.recurrent else 0.0
        return {"integrated": result, "congruence": binding, "trace": self.trace}


def specialists(snapshot):
    """Independent specialists run against one immutable snapshot in parallel."""
    if not isinstance(snapshot, dict) or set(snapshot) != {"signal", "danger", "goal"}:
        raise ValueError("exact specialist snapshot required")
    data = {key: scalar(value) for key, value in snapshot.items()}
    functions = {
        "perception": lambda: data["signal"],
        "safety": lambda: data["danger"],
        "planning": lambda: data["goal"] * (1 - data["danger"]),
    }
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks = {key: pool.submit(fn) for key, fn in functions.items()}
        return {key: task.result() for key, task in tasks.items()}


@dataclass
class Workspace:
    capacity: int = 2
    broadcast_enabled: bool = True
    inboxes: dict = field(default_factory=lambda: {"perception": [], "memory": [], "planning": []})

    def __post_init__(self):
        if type(self.capacity) is not int or not 1 <= self.capacity <= 3:
            raise ValueError("small workspace capacity required")

    def publish(self, priorities):
        if not isinstance(priorities, dict) or not priorities:
            raise ValueError("nonempty priorities required")
        for value in priorities.values():
            scalar(value)
        selected = sorted(priorities, key=lambda k: (-priorities[k], k))[:self.capacity]
        if self.broadcast_enabled:
            for name in self.inboxes:
                self.inboxes[name] = list(selected)
        return selected

    @staticmethod
    def sequential_queries(danger, novelty):
        danger, novelty = scalar(danger), scalar(novelty)
        # A two-stage query plan changes as control state changes.
        return ("safety", "memory", "planning") if danger > novelty else (
            "perception", "planning", "memory")


def infer_percept(observed, prior, reliability):
    """HOT-1 toy top-down inference under noise."""
    observed, prior, reliability = scalar(observed), scalar(prior), scalar(reliability)
    return reliability * observed + (1 - reliability) * prior


def monitor_reliability(noise):
    """An explicit reliability model, NOT proven metacognitive access."""
    if type(noise) not in (int, float) or not math.isfinite(noise) or noise < 0:
        raise ValueError("finite nonnegative noise required")
    return 1 / (1 + noise)


def update_belief(prior, observation, monitoring_weight):
    prior, observation, monitoring_weight = (
        scalar(prior), scalar(observation), scalar(monitoring_weight))
    return prior + monitoring_weight * (observation - prior)


def choose_from_belief(belief):
    return "approach" if scalar(belief) >= 0.6 else "inspect"


def quality_code(value):
    """Piecewise-linear, sparse, continuous code over five tuned channels."""
    value = scalar(value)
    position = value * 4
    left = min(int(position), 4)
    right = min(left + 1, 4)
    code = [0.0] * 5
    code[left] = 1.0 if left == right else right - position
    if right != left:
        code[right] = position - left
    return tuple(code)


@dataclass
class AttentionSchema:
    last_predicted: str = ""
    last_observed: str = ""
    prediction_errors: int = 0

    def predict(self, salience):
        if not isinstance(salience, dict) or not salience:
            raise ValueError("salience dictionary required")
        for value in salience.values():
            scalar(value)
        self.last_predicted = max(sorted(salience), key=lambda k: salience[k])
        return self.last_predicted

    def observe(self, focused):
        if not isinstance(focused, str) or not focused:
            raise ValueError("focus required")
        self.last_observed = focused
        self.prediction_errors += int(focused != self.last_predicted)

    def steer(self, salience, target):
        if target not in salience:
            raise ValueError("unknown attention target")
        changed = dict(salience)
        changed[target] = 1.0
        return changed


@dataclass
class PredictiveCoder:
    prediction: float = 0.0
    gain: float = 0.5
    learning: bool = True

    def step(self, sensory):
        sensory = scalar(sensory)
        error = sensory - self.prediction
        if self.learning:
            self.prediction += self.gain * error
        return error


@dataclass
class GoalLearner:
    values: dict = field(default_factory=lambda: {"observe": 0.5, "explore": 0.5})
    learning: bool = True

    def choose(self):
        return max(sorted(self.values), key=lambda k: self.values[k])

    def feedback(self, action, reward):
        if action not in self.values:
            raise ValueError("unknown goal")
        reward = scalar(reward)
        if self.learning:
            self.values[action] += 0.8 * (reward - self.values[action])


@dataclass
class SensorimotorModel:
    effect: dict = field(default_factory=lambda: {"left": 0.0, "right": 0.0})
    counts: dict = field(default_factory=lambda: {"left": 0, "right": 0})

    def learn(self, action, before, after):
        if action not in self.effect:
            raise ValueError("unknown action")
        if any(type(x) not in (int, float) or not math.isfinite(x) for x in (before, after)):
            raise ValueError("finite sensory values required")
        self.counts[action] += 1
        n = self.counts[action]
        self.effect[action] += ((after - before) - self.effect[action]) / n

    def choose(self, current, target):
        if any(type(x) not in (int, float) or not math.isfinite(x) for x in (current, target)):
            raise ValueError("finite control target required")
        return min(sorted(self.effect),
                   key=lambda a: abs(current + self.effect[a] - target))


@dataclass
class PrototypeCycle:
    """A bounded in-memory *example*, not an import into the live Tadash body."""
    perception: RecurrentBinder = field(default_factory=RecurrentBinder)
    workspace: Workspace = field(default_factory=Workspace)
    attention: AttentionSchema = field(default_factory=AttentionSchema)
    prediction: PredictiveCoder = field(default_factory=PredictiveCoder)
    goals: GoalLearner = field(default_factory=GoalLearner)
    body: SensorimotorModel = field(default_factory=SensorimotorModel)
    belief: float = 0.5

    def step(self, *, visual, audio, danger, goal, noise, sensory):
        perception = self.perception.observe(visual, audio)
        parallel = specialists({"signal": perception["integrated"],
                                "danger": danger, "goal": goal})
        selected = self.workspace.publish(parallel)
        query_plan = self.workspace.sequential_queries(danger, visual)
        reliability = monitor_reliability(noise)
        posterior = infer_percept(perception["integrated"], self.belief, reliability)
        self.belief = update_belief(self.belief, posterior, reliability)
        focus = self.attention.predict(parallel)
        self.attention.observe(selected[0])
        error = self.prediction.step(sensory)
        action = self.goals.choose()
        return {
            "perception": perception, "specialists": parallel,
            "workspace_selected": selected, "inboxes": {k: list(v) for k,v in self.workspace.inboxes.items()},
            "query_plan": query_plan, "attention_prediction": focus,
            "attention_observation": self.attention.last_observed,
            "attention_errors": self.attention.prediction_errors,
            "reliability": reliability, "posterior": posterior,
            "belief": self.belief, "quality_code": quality_code(posterior),
            "prediction_error": error, "chosen_goal": action,
            "predicted_effects": dict(self.body.effect),
            "interpretation": "Isolated computational prototype; no consciousness inference",
        }
