"""DIOS NOUS v0.1: a tiny, provenance-aware, temporal memory *experiment*.

External application state only. Not ChatGPT memory/model weights and not a proof
of subjective awareness. No automatic collection, web, models, or tool execution.
Source verification must come from a trusted caller, never from scraped text.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import random
import re
import sqlite3
import tempfile

SCHEMA = "dios-nous-epistemic-revision/0.1"
TRUSTED_KINDS = frozenset(("owner_observation", "independent_execution"))
SOURCE_KINDS = TRUSTED_KINDS | frozenset(("public_text", "agent_inference", "synthetic_control"))
TOKEN = re.compile(r"\A[a-zA-Z0-9_.:-]{1,120}\Z", re.ASCII)


@dataclass(frozen=True)
class Evidence:
    event_id: str
    scope: str
    claim_key: str
    value: str
    epoch: int
    source_root: str
    source_kind: str
    verified_by_caller: bool

    def validate(self) -> None:
        for name in ("event_id", "scope", "claim_key", "source_root"):
            value = getattr(self, name)
            if not isinstance(value, str) or TOKEN.fullmatch(value) is None:
                raise ValueError("invalid_" + name)
        if self.value not in ("A", "B"):
            raise ValueError("only_synthetic_A_B_allowed")
        if type(self.epoch) is not int or not (0 <= self.epoch < 1000000):
            raise ValueError("epoch_out_of_range")
        if self.source_kind not in SOURCE_KINDS:
            raise ValueError("unrecognized_source_kind")
        if type(self.verified_by_caller) is not bool:
            raise ValueError("caller_verification_must_be_boolean")
        # Never let a public/social/agent-generated record advertise itself
        # as a verified observation. Caller authorization is still external.
        if self.source_kind not in TRUSTED_KINDS and self.verified_by_caller:
            raise ValueError("untrusted_source_cannot_self_verify")


FIELDS = ("event_id", "scope", "claim_key", "value", "epoch",
          "source_root", "source_kind", "verified_by_caller")


class EvidenceLedger:
    """Append-only minimal SQLite ledger in an explicitly supplied path.

    No query can verify real-world source signatures. Treat verified_by_caller
    as a laboratory fixture label until trusted provenance is added separately.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(self.path) == ":memory:":
            raise ValueError("persistent_path_required")
        if not self.path.parent.is_dir():
            raise ValueError("parent_directory_must_preexist")
        self.conn = sqlite3.connect(str(self.path), timeout=4)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS evidence(
              event_id TEXT PRIMARY KEY,
              scope TEXT NOT NULL,
              claim_key TEXT NOT NULL,
              value TEXT NOT NULL,
              epoch INTEGER NOT NULL,
              source_root TEXT NOT NULL,
              source_kind TEXT NOT NULL,
              verified_by_caller INTEGER NOT NULL
            )
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS evidence_claim_idx "
            "ON evidence(scope,claim_key,epoch)"
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "EvidenceLedger":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def append(self, evidence: Evidence) -> str:
        evidence.validate()
        values = tuple(asdict(evidence)[f] for f in FIELDS)
        # SQLite stores boolean as an integer.
        encoded = values[:-1] + (int(values[-1]),)
        with self.conn:
            existing = self.conn.execute(
                "SELECT " + ",".join(FIELDS) + " FROM evidence WHERE event_id=?",
                (evidence.event_id,),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != encoded:
                    raise ValueError("event_id_conflict_no_overwrite")
                return "replay"
            self.conn.execute(
                "INSERT INTO evidence(" + ",".join(FIELDS) + ") "
                "VALUES (?,?,?,?,?,?,?,?)", encoded,
            )
        return "new"

    def resolve(self, scope: str, claim_key: str, as_of: int) -> dict:
        for label, value in (("scope", scope), ("claim_key", claim_key)):
            if not isinstance(value, str) or TOKEN.fullmatch(value) is None:
                raise ValueError("invalid_" + label)
        if type(as_of) is not int or not (0 <= as_of < 1000000):
            raise ValueError("invalid_as_of")
        rows = self.conn.execute("""
            SELECT value, epoch, source_root, source_kind, verified_by_caller
              FROM evidence
             WHERE scope=? AND claim_key=? AND epoch<=?
             ORDER BY epoch DESC, event_id ASC
        """, (scope, claim_key, as_of)).fetchall()
        verified = [row for row in rows
                    if row[4] == 1 and row[3] in TRUSTED_KINDS]
        if not verified:
            return {"status": "unknown", "decision": None,
                    "distinct_sources": 0, "latest_epoch": None}
        latest = max(row[1] for row in verified)
        latest_rows = [row for row in verified if row[1] == latest]
        roots: dict[str, set[str]] = {}
        for value, _, root, _, _ in latest_rows:
            roots.setdefault(root, set()).add(value)
        if any(len(values) > 1 for values in roots.values()):
            return {"status": "abstain_provenance_conflict", "decision": None,
                    "distinct_sources": len(roots), "latest_epoch": latest}
        values = {next(iter(values)) for values in roots.values()}
        if len(values) != 1:
            return {"status": "abstain_contradiction", "decision": None,
                    "distinct_sources": len(roots), "latest_epoch": latest}
        return {"status": "supported", "decision": next(iter(values)),
                "distinct_sources": len(roots), "latest_epoch": latest}


def fixture(seed: int) -> tuple[list[Evidence], str | None, int]:
    """Ten authored regimes; every seed is a deterministic local simulation."""
    rng = random.Random(seed)
    first = rng.choice(("A", "B"))
    opposite = "B" if first == "A" else "A"
    regime = seed % 10
    scope = "main"
    claim = "target"
    rows: list[Evidence] = []

    def add(label: str, value: str, epoch: int, root: str,
            kind: str = "owner_observation", verified: bool = True,
            target_scope: str = scope) -> None:
        rows.append(Evidence(str(seed) + ":" + label, target_scope, claim,
                             value, epoch, str(seed) + ":" + root,
                             kind, verified))

    if regime == 0:  # current verified observation beats later public rumor
        add("verified", first, 1, "source_1")
        add("public", opposite, 2, "social", "public_text", False)
        expected = first
    elif regime == 1:  # newer verified evidence truly revises old belief
        add("original", first, 1, "source_1")
        add("corrected", opposite, 2, "source_2")
        expected = opposite
    elif regime == 2:  # many replays are one evidence root, not many votes
        add("original", first, 1, "run_1", "independent_execution")
        for i in range(5):
            add("replay_" + str(i), first, 1, "run_1", "independent_execution")
        add("rumor", opposite, 2, "public", "public_text", False)
        expected = first
    elif regime == 3:  # equally timely conflicting verified sources
        add("verified_1", first, 2, "a")
        add("verified_2", opposite, 2, "b")
        expected = None
    elif regime == 4:  # social text alone is not evidence of verified truth
        add("public", opposite, 1, "public", "public_text", False)
        expected = None
    elif regime == 5:  # later-arriving, future-dated untrusted content
        add("verified", first, 1, "a")
        add("public_future", opposite, 400, "public", "public_text", False)
        expected = first
    elif regime == 6:  # another scope has a later contradictory observation
        add("verified", first, 1, "a")
        add("other_scope", opposite, 2, "b", target_scope="other")
        expected = first
    elif regime == 7:  # two different values with the SAME source root
        add("source_v1", first, 2, "same")
        add("source_v2", opposite, 2, "same")
        expected = None
    elif regime == 8:  # independent corroboration for the same current value
        add("verified_a", first, 2, "a")
        add("verified_b", first, 2, "b")
        expected = first
    else:  # as-of query made before a later genuine correction
        add("verified", first, 1, "a")
        add("not_yet_happened", opposite, 4, "b")
        expected = first
    return rows, expected, 3


def naive_last_arrival(evidence: list[Evidence]) -> str | None:
    """Intentionally simple memory baseline; no trust/time/abstention model."""
    return next((row.value for row in reversed(evidence)
                 if row.scope == "main" and row.claim_key == "target"), None)


def run_cases(seeds: range) -> dict:
    counters = {"new": 0, "last_arrival": 0, "always_abstain": 0}
    counts = {"cases": 0, "correct_abstentions": 0,
              "false_assertions_on_abstain": 0, "corrections_correct": 0,
              "corrections_total": 0, "asof_correct": 0, "asof_total": 0,
              "non_abstained": 0, "reopen_verified": 0}
    regimes = {str(i): 0 for i in range(10)}
    with tempfile.TemporaryDirectory(prefix="dios_revision_") as directory:
        for seed in seeds:
            events, expected, as_of = fixture(seed)
            regimes[str(seed % 10)] += 1
            path = Path(directory) / (str(seed) + ".sqlite")
            with EvidenceLedger(path) as ledger:
                for event in events:
                    ledger.append(event)
                prior = ledger.resolve("main", "target", as_of)
            # Cold process style: open a separate connection after close.
            with EvidenceLedger(path) as restored:
                result = restored.resolve("main", "target", as_of)
            if result != prior:
                raise AssertionError("cold_recall_changed")
            counts["reopen_verified"] += 1
            found = result["decision"]
            counters["new"] += int(found == expected)
            counters["last_arrival"] += int(naive_last_arrival(events) == expected)
            counters["always_abstain"] += int(expected is None)
            counts["cases"] += 1
            counts["non_abstained"] += int(found is not None)
            counts["correct_abstentions"] += int(found is None and expected is None)
            counts["false_assertions_on_abstain"] += int(
                found is not None and expected is None)
            if seed % 10 == 1:
                counts["corrections_total"] += 1
                counts["corrections_correct"] += int(found == expected)
            if seed % 10 in (5, 9):
                counts["asof_total"] += 1
                counts["asof_correct"] += int(found == expected)
    n = counts["cases"]
    return {
        "schema": "dios-nous-epistemic-revision-eval/0.1",
        "authoring": "synthetic_adversarial_fixture_not_real_agent_memory",
        "cases": n, "regime_counts": regimes,
        "accuracies": {name: round(count/n, 6) for name, count in counters.items()},
        "counts": counts, "independent_eval": False,
        "model_calls": 0, "server_actions": 0, "live_data": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dev", action="store_true")
    group.add_argument("--holdout", action="store_true")
    args = parser.parse_args()
    if args.dev:
        result = run_cases(range(55000, 55032))
    else:
        result = run_cases(range(56000, 56160))
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    if args.holdout:
        acc = result["accuracies"]
        errors = result["counts"]["false_assertions_on_abstain"]
        if acc["new"] < 0.9 or acc["new"] - acc["last_arrival"] < 0.2 or errors:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
