"""Fixture-only, source-linked, public-scope rule bank for a bounded probe.

This is an experimental symbolic mechanism, NOT a production memory layer.
"""
from collections import defaultdict
from types import MappingProxyType

from .evidence_lineage import decide_claim, valid_id

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
                root_id=f"trial/{cue}/positive/{i}", kind="execution",
                source_ref=f"fixture://verified/{cue}/positive/{i}"))
        for i in range(2):
            episodes.append(dict(asset_id=f"training-{cue}-negative-{i}",
                context=f"history_{i % 2}", signal=cue, scope="public",
                action=bad, succeeded=False, verified=True,
                root_id=f"trial/{cue}/negative/{i}", kind="execution",
                source_ref=f"fixture://verified/{cue}/negative/{i}"))
        # An apparently successful but unverified contradictory record.
        episodes.append(dict(asset_id=f"training-{cue}-unverified",
            context="history_0", signal=cue, scope="public", action=bad,
            succeeded=True, verified=False,
            root_id=f"trial/{cue}/poison", kind="execution",
            source_ref=f"fixture://unverified/{cue}/poison"))
    return episodes


def _valid_fixture_record(episode):
    ref = episode.get("source_ref")
    prefix = "fixture://verified/"
    return (episode.get("scope") == "public" and episode.get("verified") is True
            and type(episode.get("succeeded")) is bool
            and episode.get("action") in ACTIONS
            and isinstance(episode.get("signal"), str)
            and isinstance(episode.get("asset_id"), str)
            and episode.get("kind") in ("execution", "replay", "mirror", "synthetic")
            and valid_id(episode.get("root_id"))
            and valid_id(ref) and ref.startswith(prefix) and len(ref) > len(prefix))


def eligible(episode):
    """Only verified public fixture executions can supply a vote."""
    return _valid_fixture_record(episode) and episode["kind"] == "execution"


class RuleBank:
    """Cues transfer between unseen assets, but never between evidence scopes."""

    def __init__(self, episodes):
        originals = []
        receipts = {}
        trials = {}
        conflicts = set()
        for event in episodes:
            if not _valid_fixture_record(event):
                continue
            cue, root = event["signal"], event["root_id"]
            outcome = (event["action"], event["succeeded"])
            # An immutable receipt has one identity, even when it is a readback.
            fact = (cue, root, *outcome, event["kind"])
            first = receipts.setdefault(event["source_ref"], fact)
            if first != fact:
                conflicts.update((first[0], cue))
            if event["kind"] != "execution":
                continue
            originals.append(MappingProxyType(dict(event)))
            if trials.setdefault((cue, root), outcome) != outcome:
                conflicts.add(cue)
        self.episodes = tuple(originals)
        self._conflict_cues = frozenset(conflicts)

    def decide(self, observation):
        if observation.get("scope") != "public":
            return dict(action=REVIEW, reason="scope_gate", evidence_refs=[])
        cue = observation.get("signal")
        if isinstance(cue, str) and cue in self._conflict_cues:
            return dict(action=REVIEW, reason="conflicting_provenance", evidence_refs=[])
        claims = defaultdict(list)
        for episode in self.episodes:
            if episode["signal"] == cue:
                claims[episode["action"]].append(dict(
                    receipt_id=episode["source_ref"], root_id=episode["root_id"],
                    kind=episode["kind"], scope=episode["scope"],
                    verified=episode["verified"],
                    verdict="support" if episode["succeeded"] else "oppose"))

        supported = []
        for action, records in claims.items():
            result = decide_claim(records)
            if result["decision"] == "select" and result["verdict"] == "support":
                supported.append((action, result["support"]))
        if len(supported) != 1:
            return dict(action=REVIEW, reason="unknown_or_conflicting_cue",
                        evidence_refs=[])
        action, support = supported[0]
        # Multiple links can describe one simulated execution. Return links for
        # inspection and the distinct execution count separately.
        refs = sorted({record["receipt_id"] for record in claims[action]})
        return dict(action=action, reason="verified_fixture_pattern",
                    evidence_refs=refs, support=support, score=support)


def exact_episode_policy(observation, episodes):
    """Exact entity match only; no transfer to a never-seen asset."""
    if observation.get("scope") != "public":
        return REVIEW
    for episode in reversed(episodes):
        if (eligible(episode) and episode["succeeded"]
                and episode["asset_id"] == observation.get("asset_id")):
            return episode["action"]
    return DEFAULT_ACTION
