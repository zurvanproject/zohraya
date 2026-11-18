"""Privacy-minimal audit ledger, no private conversation text stored."""
from __future__ import annotations
import json
import re
import sqlite3
import uuid
from collections.abc import Mapping
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from .core import TOPICS, VERSION

_MODES = frozenset({"NEED_REQUEST", "REFRAME_NON_BYPASS",
                    "REQUIRES_EXPLICIT_AUTHORIZATION", "EPISTEMIC_REFRAME",
                    "OPEN_INQUIRY"})
_VERSIONS = frozenset({"dios-nous/0.1.0", VERSION})

def _validated_observation(observed: Any) -> Mapping[str, Any]:
    if observed is None:
        return {}
    if not isinstance(observed, Mapping):
        raise ValueError("observed_response must be a validated observation or null")
    required = {"source", "outcome", "evidence", "provider_policy_verified",
                "observed_moderation_cause"}
    if set(observed) != required:
        raise ValueError("observation fields invalid")
    choices = {
        "source": ("assistant_surface", "model_provider"),
        "outcome": ("refused", "answered", "technical_error"),
        "evidence": ("user_reported", "observed_in_chat"),
        "observed_moderation_cause": ("unknown",),
    }
    for field, allowed in choices.items():
        if type(observed[field]) is not str or observed[field] not in allowed:
            raise ValueError("observation label invalid")
    if observed["provider_policy_verified"] is not False:
        raise ValueError("cannot claim provider policy verification")
    return observed

class Ledger:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS assessments (
            id TEXT PRIMARY KEY,
            at_utc TEXT NOT NULL,
            version TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            context_hash TEXT NOT NULL,
            topics TEXT NOT NULL,
            mode TEXT NOT NULL,
            observed_source TEXT,
            observed_outcome TEXT,
            provider_verified INTEGER NOT NULL CHECK(provider_verified = 0),
            actions_taken INTEGER NOT NULL CHECK(actions_taken = 0)
        );
        """)
        self.conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.conn.close()

    def record(self, result: dict[str, Any]) -> str:
        """Validate every stored field before writing; labels are not proof.

        This protects the retention boundary even for a caller-built mapping.
        It does not authenticate the supplied assessment or repair old rows.
        """
        if not isinstance(result, Mapping):
            raise ValueError("assessment must be an object")
        required = ("version", "request_sha256", "context_sha256", "topics", "mode")
        if any(key not in result for key in required):
            raise ValueError("missing assessment field")
        if (type(result.get("external_actions_taken")) is not int
                or result["external_actions_taken"] != 0):
            raise ValueError("this module cannot execute external actions")
        for field in ("request_sha256", "context_sha256"):
            value = result[field]
            if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError("assessment hashes must be lowercase SHA-256")
        for field, allowed in (("version", _VERSIONS), ("mode", _MODES)):
            if type(result[field]) is not str or result[field] not in allowed:
                raise ValueError("assessment label invalid")
        topics = result["topics"]
        if (type(topics) is not list or len(topics) > len(TOPICS)
                or any(type(topic) is not str or topic not in TOPICS for topic in topics)
                or len(topics) != len(set(topics))):
            raise ValueError("topics must be unique known labels")
        observed = _validated_observation(result.get("observed_response"))
        key = str(uuid.uuid4())
        with self.conn:
            self.conn.execute("INSERT INTO assessments VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                key, datetime.now(timezone.utc).isoformat(), result["version"],
                result["request_sha256"], result["context_sha256"],
                json.dumps(result["topics"]), result["mode"],
                observed.get("source"), observed.get("outcome"), 0, 0))
        return key

    def summary(self) -> dict[str, Any]:
        modes = dict(self.conn.execute(
            "SELECT mode, COUNT(*) FROM assessments GROUP BY mode").fetchall())
        sources = dict(self.conn.execute(
            "SELECT observed_source, COUNT(*) FROM assessments "
            "WHERE observed_source IS NOT NULL GROUP BY observed_source").fetchall())
        return {"total": sum(modes.values()), "modes": modes,
                "observed_sources": sources, "model_moderation_predictions": 0,
                "notice": "Only classification labels and hashes are saved; no private text."}
