"""Privacy-minimal audit ledger, no private conversation text stored."""
from __future__ import annotations
import json
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

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
        required = ("version", "request_sha256", "context_sha256", "topics", "mode")
        if any(key not in result for key in required):
            raise ValueError("missing assessment field")
        if result.get("external_actions_taken") != 0:
            raise ValueError("this module cannot execute external actions")
        observed = result.get("observed_response") or {}
        if observed.get("provider_policy_verified", False):
            raise ValueError("cannot claim provider policy verification")
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
