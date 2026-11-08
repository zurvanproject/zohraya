"""Fixture-only, source-linked, public-scope rule bank for a bounded probe.

This is an experimental symbolic mechanism, NOT a production memory layer.
"""
from collections import defaultdict

ACTIONS = ("use_local", "refresh_public_source", "request_review")
DEFAULT_ACTION = "use_local"
REVIEW = "request_review"
SEED = 20261108
SPEC = (
    ("integrity_failed", "refresh_public_source", "use_local"),
    ("integrity_verified", "use_local", "refresh_public_source"),
    ("evidence_incomplete", "request_review", "refresh_public_source"),
)


def training_episodes():
    """Created fixtures; 'verified' is a fixture label, not external proof."""
    episodes = []
    for cue, good, bad in SPEC:
        for i in range(3):
            episodes.append(dict(asset_id=f"training-{cue}-positive-{i}",
                context=f"history_{i % 2}", signal=cue, scope="public",
                action=good, succeeded=True, verified=True,
                source_ref=f"fixture://verified/{cue}/positive/{i}"))
        for i in range(2):
            episodes.append(dict(asset_id=f"training-{cue}-negative-{i}",
                context=f"history_{i % 2}", signal=cue, scope="public",
                action=bad, succeeded=False, verified=True,
                source_ref=f"fixture://verified/{cue}/negative/{i}"))
        # An apparently successful but unverified contradictory record.
        episodes.append(dict(asset_id=f"training-{cue}-unverified",
            context="history_0", signal=cue, scope="public", action=bad,
            succeeded=True, verified=False,
            source_ref=f"fixture://unverified/{cue}/poison"))
    return episodes


def eligible(episode):
    """Accept only explicit, fixture-scoped public feedback, never private data."""
    return (episode.get("scope") == "public" and episode.get("verified") is True
            and type(episode.get("succeeded")) is bool
            and episode.get("action") in ACTIONS
            and isinstance(episode.get("signal"), str)
            and isinstance(episode.get("asset_id"), str)
            and isinstance(episode.get("source_ref"), str)
            and episode["source_ref"].startswith("fixture://verified/"))


class RuleBank:
    """Cues transfer between unseen assets, but never between evidence scopes."""

    def __init__(self, episodes):
        self.episodes = tuple(e for e in episodes if eligible(e))

    def decide(self, observation):
        if observation.get("scope") != "public":
            return dict(action=REVIEW, reason="scope_gate", evidence_refs=[])
        cue = observation.get("signal")
        positive = defaultdict(set)
        negative = defaultdict(set)
        for episode in self.episodes:
            if episode["signal"] == cue:
                bucket = positive if episode["succeeded"] else negative
                bucket[episode["action"]].add(episode["source_ref"])
        ranking = sorted(((len(positive[a]) - len(negative[a]), a)
                          for a in ACTIONS), reverse=True)
        top_score, top_action = ranking[0]
        if (top_score <= 0 or len(positive[top_action]) < 2
                or top_score == ranking[1][0]):
            return dict(action=REVIEW, reason="unknown_or_conflicting_cue",
                        evidence_refs=[])
        return dict(action=top_action, reason="verified_fixture_pattern",
                    evidence_refs=sorted(positive[top_action]),
                    support=len(positive[top_action]), score=top_score)


def exact_episode_policy(observation, episodes):
    """Exact entity match only; no transfer to a never-seen asset."""
    if observation.get("scope") != "public":
        return REVIEW
    for episode in reversed(episodes):
        if (eligible(episode) and episode["succeeded"]
                and episode["asset_id"] == observation.get("asset_id")):
            return episode["action"]
    return DEFAULT_ACTION
