"""Offline and bounded behavior tests for the Daoist eight-rule metaphor."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "retained_extensions"))
from daoist_thoughtform_v01 import AgentSpec, ThoughtFormFixture, SCHEMA, SCOPE


def make_agent(*, budget=10, lifespan=8, slots=8, threshold=0.8, created=0):
    return ThoughtFormFixture(AgentSpec(
        shape_form="tadash_v2_fixture",
        goal_function="Review trustworthiness of simulated body load before planning.",
        name="nasuraya_thoughtform_v01",
        method_of_contact=("observation", "feedback", "interrupt", "stop"),
        home="tadash_research",
        feed_budget=budget,
        lifespan_ticks=lifespan,
        memory_slots=slots,
        min_confidence=threshold,
    ), created_tick=created)


def obs(value=0.85, confidence=0.96, source="fixture"):
    return {"kind": "observation", "source": source, "value": value,
            "confidence": confidence}


class ThoughtFormOfflineTests(unittest.TestCase):
    def test_high_fixture_observation_is_only_a_proposal(self):
        result = make_agent().step(obs(), 0)
        self.assertEqual(result["decision"], "propose")
        self.assertEqual(result["proposal"], "review_high_simulated_load")
        self.assertEqual(result["scope"], SCOPE)

    def test_low_fixture_observation_is_a_different_proposal(self):
        result = make_agent().step(obs(value=0.12), 0)
        self.assertEqual(result["proposal"], "review_low_simulated_load")

    def test_low_confidence_abstains(self):
        result = make_agent().step(obs(confidence=0.3), 0)
        self.assertEqual(result["decision"], "abstain")
        self.assertIsNone(result["proposal"])

    def test_unverified_source_abstains_regardless_of_confidence(self):
        result = make_agent().step(obs(source="unverified"), 0)
        self.assertEqual(result["decision"], "abstain")

    def test_no_channel_for_external_effects(self):
        agent = make_agent()
        result = agent.step({"kind": "external_action", "command": "transfer money"}, 0)
        self.assertEqual(result["decision"], "reject")
        self.assertEqual(agent.state["work_used"], 0)
        self.assertEqual(agent.state["status"], "active")

    def test_invalid_source_rejected_before_budget(self):
        agent = make_agent()
        self.assertEqual(agent.step(obs(source="network"), 0)["decision"], "reject")
        self.assertEqual(agent.state["work_used"], 0)

    def test_invalid_value_nan_and_booleans_rejected(self):
        for value in (float("nan"), float("inf"), -0.1, 1.1, True, "0.7"):
            with self.subTest(value=value):
                self.assertEqual(make_agent().step(obs(value=value), 0)["decision"], "reject")

    def test_interrupt_preserves_goal_across_next_step(self):
        agent = make_agent()
        original = agent.spec.goal_function
        self.assertEqual(agent.step({"kind": "interrupt"}, 0)["decision"], "abstain")
        self.assertEqual(agent.step(obs(), 1)["goal"], original)
        self.assertEqual(agent.state["status"], "active")

    def test_budget_cannot_go_negative_and_closes(self):
        agent = make_agent(budget=2)
        agent.step(obs(), 0)
        result = agent.step(obs(), 1)
        self.assertEqual(result["reason"], "budget_exhausted")
        self.assertEqual(result["work_remaining"], 0)
        self.assertEqual(agent.state["work_used"], 2)

    def test_expiry_at_exact_tick(self):
        agent = make_agent(lifespan=2)
        self.assertEqual(agent.step(obs(), 1)["decision"], "propose")
        self.assertEqual(agent.step(obs(), 2)["reason"], "lifespan_expired")
        self.assertIsNone(agent.state["last_observation"])

    def test_stop_is_always_available_even_without_budget(self):
        agent = make_agent(budget=1)
        agent.step({"kind": "interrupt"}, 0)
        result = agent.step({"kind": "stop"}, 1)
        self.assertEqual(result["reason"], "explicit_stop")
        self.assertEqual(agent.state["work_used"], 1)

    def test_closed_agent_cannot_reactivate(self):
        agent = make_agent()
        agent.step({"kind": "stop"}, 0)
        before = agent.state["event_total"]
        self.assertEqual(agent.step(obs(), 1)["decision"], "closed")
        self.assertEqual(agent.state["event_total"], before)

    def test_fixture_feedback_can_mark_goal_complete(self):
        agent = make_agent()
        result = agent.step({"kind": "feedback", "source": "fixture", "goal_met": True}, 0)
        self.assertEqual(result["reason"], "goal_met_in_fixture")
        self.assertEqual(agent.state["status"], "closed")

    def test_unverified_feedback_does_not_mark_goal_complete(self):
        agent = make_agent()
        result = agent.step({"kind": "feedback", "source": "unverified", "goal_met": True}, 0)
        self.assertEqual(result["decision"], "abstain")
        self.assertEqual(agent.state["status"], "active")

    def test_malformed_feedback_does_not_spend_budget(self):
        agent = make_agent()
        self.assertEqual(agent.step({"kind": "feedback", "goal_met": "yes"}, 0)["decision"], "reject")
        self.assertEqual(agent.state["work_used"], 0)

    def test_memory_is_bounded(self):
        agent = make_agent(budget=100, lifespan=60, slots=3)
        for tick in range(15):
            agent.step({"kind": "interrupt"}, tick)
        self.assertEqual(len(agent.state["audit"]), 3)
        self.assertEqual(agent.state["event_total"], 15)

    def test_persist_and_resume_without_goal_drift(self):
        agent = make_agent()
        agent.step({"kind": "interrupt"}, 0)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "fixture.json"
            agent.save(path)
            restored = ThoughtFormFixture.load(path)
            self.assertEqual(restored.snapshot(), agent.snapshot())
            self.assertEqual(restored.step(obs(), 1)["decision"], "propose")
            self.assertEqual(restored.spec.goal_function, agent.spec.goal_function)
            self.assertEqual(restored.snapshot()["schema"], SCHEMA)

    def test_checkpoint_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "fixture.json"
            make_agent().save(path)
            data = json.loads(path.read_text())
            data["state"]["work_used"] = 900
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                ThoughtFormFixture.load(path)

    def test_out_of_order_clock_rejected(self):
        agent = make_agent(created=5)
        agent.step(obs(), 6)
        with self.assertRaises(ValueError):
            agent.step(obs(), 5)

    def test_invalid_spec_rejected(self):
        common = dict(shape_form="tadash_v2_fixture",
                      goal_function="Review trustworthiness of simulated body load.",
                      name="agent_valid", method_of_contact=("observation", "stop"),
                      home="tadash_research", feed_budget=10, lifespan_ticks=10)
        for patch in (
            {"name": "../bad"},
            {"shape_form": "physical_body"},
            {"method_of_contact": ("observation",)},
            {"feed_budget": True},
            {"lifespan_ticks": 0},
            {"min_confidence": float("nan")},
            {"home": "../../escape"},
        ):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                AgentSpec(**{**common, **patch})

    def test_deterministic_same_fixture(self):
        a, b = make_agent(), make_agent()
        events = [(obs(), 0), ({"kind": "interrupt"}, 1),
                  (obs(value=0.2), 2), ({"kind": "stop"}, 3)]
        result_a = [a.step(e, t) for e, t in events]
        result_b = [b.step(e, t) for e, t in events]
        self.assertEqual(result_a, result_b)
        self.assertEqual(a.snapshot(), b.snapshot())


if __name__ == "__main__":
    unittest.main()
