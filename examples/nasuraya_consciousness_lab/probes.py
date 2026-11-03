"""14 bounded, causal *toy* experiments: each has an explicit counterfactual.

Pass means the small, authored component behaves as specified. It does not
certify a deployed cognitive architecture, phenomenal consciousness, or any
published AI-consciousness benchmark. No randomness, network or paid API.
"""
from . import mechanisms as m
from .indicators import BY_CODE


def probes():
    outcomes = {}

    # RPT-1: matched current observation, different internal history.
    recursive = m.RecurrentBinder(recurrent=True)
    first = recursive.observe(0.8, 0.8)["integrated"]
    second = recursive.observe(0.8, 0.8)["integrated"]
    ablated = m.RecurrentBinder(recurrent=False)
    without = (ablated.observe(0.8, 0.8)["integrated"],
               ablated.observe(0.8, 0.8)["integrated"])
    outcomes["RPT-1"] = second > first and abs(without[1] - without[0]) < 1e-12

    # RPT-2: same visual level, shuffle the cross-modal relation.
    close = m.RecurrentBinder(recurrent=False).observe(0.8, 0.8)
    shuffled = m.RecurrentBinder(recurrent=False).observe(0.8, 0.2)
    outcomes["RPT-2"] = (close["congruence"] > shuffled["congruence"] and
                         close["integrated"] > shuffled["integrated"])

    # GWT-1: independent specialist computations on one snapshot.
    a = m.specialists({"signal": 0.2, "danger": 0.8, "goal": 0.8})
    b = m.specialists({"signal": 0.2, "danger": 0.1, "goal": 0.8})
    outcomes["GWT-1"] = (set(a) == {"perception", "safety", "planning"} and
                         a["perception"] == b["perception"] and
                         a["safety"] != b["safety"] and
                         a["planning"] != b["planning"])

    # GWT-2: matched items, change priority and capacity.
    limited = m.Workspace(capacity=1)
    choices = (limited.publish({"a": 0.8, "b": 0.3}),
               limited.publish({"a": 0.8, "b": 0.9}))
    unlimited = m.Workspace(capacity=3).publish({"a": 0.8, "b": 0.3})
    outcomes["GWT-2"] = choices == (["a"], ["b"]) and len(unlimited) == 2

    # GWT-3: causal delivery across specialists vs matched silenced bus.
    live = m.Workspace(capacity=1, broadcast_enabled=True)
    silent = m.Workspace(capacity=1, broadcast_enabled=False)
    live.publish({"danger": 0.9, "goal": 0.2})
    silent.publish({"danger": 0.9, "goal": 0.2})
    outcomes["GWT-3"] = (all(v == ["danger"] for v in live.inboxes.values())
                         and all(not v for v in silent.inboxes.values()))

    # GWT-4: change state, observe ordered query intervention.
    q1 = m.Workspace.sequential_queries(0.9, 0.1)
    q2 = m.Workspace.sequential_queries(0.1, 0.9)
    outcomes["GWT-4"] = q1 != q2 and q1[0] == "safety" and q2[0] == "perception"

    # HOT-1: priors influence uncertain, but not fully reliable sensory input.
    top_a = m.infer_percept(0.5, 0.1, 0.2)
    top_b = m.infer_percept(0.5, 0.9, 0.2)
    no_prior = (m.infer_percept(0.5, 0.1, 1.0),
                m.infer_percept(0.5, 0.9, 1.0))
    outcomes["HOT-1"] = top_b > top_a and no_prior[0] == no_prior[1]

    # HOT-2: pre-feedback reliability separates a clean and corrupted input.
    high, low = m.monitor_reliability(0.1), m.monitor_reliability(9.0)
    score = (high - 1) ** 2 + (low - 0) ** 2
    swapped_score = (low - 1) ** 2 + (high - 0) ** 2
    outcomes["HOT-2"] = score < swapped_score and high > low

    # HOT-3: metacognitive veto changes a belief and the next policy decision.
    reliable = m.update_belief(0.4, 1.0, 1.0)
    discounted = m.update_belief(0.4, 1.0, 0.0)
    outcomes["HOT-3"] = (m.choose_from_belief(reliable) == "approach" and
                         m.choose_from_belief(discounted) == "inspect")

    # HOT-4: two active channels, smooth boundary transition vs hard labels.
    left, right = m.quality_code(0.4999), m.quality_code(0.5001)
    outcomes["HOT-4"] = (max(abs(x-y) for x,y in zip(left,right)) < 0.01 and
                         all(sum(x > 0 for x in code) <= 2 for code in (left,right))
                         and all(abs(sum(code) - 1) < 1e-12 for code in (left,right)))

    # AST-1: forecast, observe, and steer a future attentional selection.
    attention = m.AttentionSchema()
    old = attention.predict({"safety": 0.8, "memory": 0.2})
    attention.observe(old)
    controlled = attention.steer({"safety": 0.8, "memory": 0.2}, "memory")
    new = attention.predict(controlled)
    attention.observe(new)
    outcomes["AST-1"] = (old == "safety" and new == "memory" and
                         attention.prediction_errors == 0)

    # PP-1: feed-forward expectation with vs without error correction.
    adaptive = m.PredictiveCoder()
    frozen = m.PredictiveCoder(learning=False)
    errors = [abs(adaptive.step(0.8)) for _ in range(5)]
    control = [abs(frozen.step(0.8)) for _ in range(5)]
    outcomes["PP-1"] = errors[-1] < errors[0] and control[-1] == control[0]

    # AE-1: same reward reversal; learn rather than perpetually retry failure.
    adaptive = m.GoalLearner()
    frozen = m.GoalLearner(learning=False)
    initial = adaptive.choose()
    adaptive.feedback(initial, 0)
    frozen.feedback(initial, 0)
    outcomes["AE-1"] = (adaptive.choose() != initial and frozen.choose() == initial)

    # AE-2: learn effects from feedback, choose an appropriate unseen target.
    body = m.SensorimotorModel()
    baseline = m.SensorimotorModel()
    body.learn("left", 0, -1)
    body.learn("right", 0, 1)
    outcomes["AE-2"] = (body.choose(0, 0.8) == "right" and
                         body.choose(0, -0.8) == "left" and
                         baseline.choose(0, 0.8) != body.choose(0, 0.8))

    if set(outcomes) != set(BY_CODE):
        raise AssertionError("missing an indicator probe")
    return {
        code: {"probe_passed": bool(passed),
               "source": "examples/nasuraya_consciousness_lab/probes.py",
               "scope": "isolated_toy_prototype"}
        for code, passed in outcomes.items()
    }
