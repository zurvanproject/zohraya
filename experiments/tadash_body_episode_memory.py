"""One-way, local, restartable simulated body memory v0.2 (no live wiring).

Store command, sensory source fingerprint, trajectory digests and an inferred
*research label* in an append-only hash-chained SQLite stream. Hashes catch
accidental corruption; they do not authenticate an adversarial database.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path

from experiments.tadash_embodied_origin import _validated, source_identity
from experiments.tadash_temporal_proprioception import classify_temporal

GENESIS = "0" * 64
ACCEPTED_STATES = frozenset((
    "no_detectable_change", "command_consistent",
    "unexplained_change", "command_outcome_mismatch",
    "uncertain_noise_or_weak_signal", "unverified",
))


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":"))


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def valid_identifier(value):
    return (isinstance(value, str) and 1 <= len(value) <= 96
            and all(c.isalnum() or c in "_-:." for c in value))


class IntegrityError(RuntimeError):
    pass


class BodyEventLedger:
    """Exactly-once *local SQLite transaction* for reproducible synthetic episodes."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                last_ordinal INTEGER NOT NULL DEFAULT 0,
                head_hash TEXT NOT NULL DEFAULT '""" + GENESIS + """'
            )""")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                session_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                PRIMARY KEY (session_id, ordinal),
                UNIQUE (session_id, event_id),
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )""")

    def close(self):
        self.db.close()

    def _verify(self, session_id):
        row = self.db.execute(
            "SELECT last_ordinal, head_hash FROM sessions WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        records = self.db.execute(
            "SELECT ordinal, event_id, payload_json, prev_hash, event_hash "
            "FROM events WHERE session_id = ? ORDER BY ordinal", (session_id,)
        ).fetchall()
        if row is None:
            if records:
                raise IntegrityError("orphaned_events")
            return 0, GENESIS, []
        expected_ordinal, previous = 0, GENESIS
        output = []
        for ordinal, event_id, payload_json, prev_hash, event_hash in records:
            expected_ordinal += 1
            if ordinal != expected_ordinal or prev_hash != previous:
                raise IntegrityError("broken_event_sequence")
            try:
                payload = json.loads(payload_json)
                if canonical(payload) != payload_json:
                    raise IntegrityError("noncanonical_payload")
            except (TypeError, ValueError) as exc:
                raise IntegrityError("invalid_event_json") from exc
            if (payload.get("event_id") != event_id or
                    payload.get("ordinal") != ordinal or
                    payload.get("session_id") != session_id):
                raise IntegrityError("event_identity_mismatch")
            computed = digest(previous + "\n" + payload_json)
            if event_hash != computed:
                raise IntegrityError("event_hash_mismatch")
            previous = computed
            output.append({"payload": payload, "hash": computed})
        if row != (expected_ordinal, previous):
            raise IntegrityError("session_head_mismatch")
        return expected_ordinal, previous, output

    def snapshot(self, session_id):
        if not valid_identifier(session_id):
            raise ValueError("invalid_session_id")
        _, head, output = self._verify(session_id)
        return {"session_id": session_id, "head": head,
                "events": output, "count": len(output)}

    def self_model(self, session_id):
        """Verified, descriptive history of *simulated* bodily predictions.

        This is a summary over ledger evidence. It is not a subjective self,
        an independent source of sensory data or a generator of goals.
        """
        snapshot = self.snapshot(session_id)
        records = [item["payload"] for item in snapshot["events"]]
        counts = {name: sum(p["assessment_state"] == name for p in records)
                  for name in sorted(ACCEPTED_STATES)}
        commanded = sum(abs(p["command_nm"]) > 1e-9 for p in records)
        errors = [p["residual"] for p in records]
        last = records[-1] if records else None
        result = {
            "kind": "descriptive_simulated_body_history_v0.2",
            "session_id": session_id,
            "episode_count": len(records),
            "commanded_episodes": commanded,
            "episode_states": counts,
            "last_episode_state": last["assessment_state"] if last else None,
            "last_command_nm": last["command_nm"] if last else None,
            "last_source_sha256": last["source_sha256"] if last else None,
            "maximum_prediction_residual": max(errors) if errors else None,
            "uncertainty_fraction": (
                (counts["uncertain_noise_or_weak_signal"] + counts["unverified"])
                / len(records) if records else None
            ),
            "verified_ledger_head": snapshot["head"],
            "read_only": True,
        }
        result["summary_sha256"] = digest(canonical(result))
        return result

    def append(self, session_id, event_id, ordinal, intent_nm,
               reference, prediction, actual):
        if not valid_identifier(session_id) or not valid_identifier(event_id):
            raise ValueError("invalid_event_identifier")
        if type(ordinal) is not int or ordinal < 1:
            raise ValueError("invalid_ordinal")
        if type(intent_nm) not in (int, float) or not math.isfinite(intent_nm):
            raise ValueError("invalid_intent")
        trusted_sha = source_identity()["sha256"]
        if not all(_validated(t, trusted_sha) for t in (reference, prediction, actual)):
            raise ValueError("source_untrusted_or_nonfinite_telemetry")
        outcome = classify_temporal(reference, prediction, actual, intent_nm)
        if outcome["state"] not in ACCEPTED_STATES or outcome["state"] == "unverified":
            raise ValueError("unverified_command_or_prediction")
        trace_digests = {
            "reference": digest(canonical(reference)),
            "prediction": digest(canonical(prediction)),
            "observation": digest(canonical(actual)),
        }
        payload = {
            "schema": "tadash.body-episode.v0.2",
            "session_id": session_id, "event_id": event_id, "ordinal": ordinal,
            "command_nm": float(intent_nm),
            "source_sha256": trusted_sha,
            "source_kind": "pinned_native_mujoco_simulation",
            "trace_digests": trace_digests,
            "native_final_time_s": actual["frames"][-1]["t_s"],
            "assessment_state": outcome["state"],
            "residual": outcome["residual"],
            "supported_proprioceptive_channels": outcome["supported_proprioceptive_channels"],
        }
        serialized = canonical(payload)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            count, head, _ = self._verify(session_id)
            existing = self.db.execute(
                "SELECT payload_json, event_hash FROM events "
                "WHERE session_id = ? AND event_id = ?",
                (session_id, event_id)).fetchone()
            if existing:
                if existing[0] != serialized:
                    raise ValueError("duplicate_event_conflict")
                self.db.execute("COMMIT")
                return {"replay": True, "event_hash": existing[1],
                        "assessment_state": outcome["state"], "ordinal": ordinal}
            if ordinal != count + 1:
                raise ValueError("nonmonotone_or_gap_ordinal")
            event_hash = digest(head + "\n" + serialized)
            if count == 0:
                self.db.execute("INSERT INTO sessions (session_id, last_ordinal, head_hash) "
                                "VALUES (?,?,?)", (session_id, 0, GENESIS))
            self.db.execute(
                "INSERT INTO events (session_id, ordinal, event_id, payload_json, prev_hash, event_hash) "
                "VALUES (?,?,?,?,?,?)",
                (session_id, ordinal, event_id, serialized, head, event_hash))
            self.db.execute(
                "UPDATE sessions SET last_ordinal=?, head_hash=? WHERE session_id=?",
                (ordinal, event_hash, session_id))
            self.db.execute("COMMIT")
            return {"replay": False, "event_hash": event_hash,
                    "assessment_state": outcome["state"], "ordinal": ordinal}
        except Exception:
            self.db.execute("ROLLBACK")
            raise
