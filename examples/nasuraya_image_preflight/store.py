"""Local audit ledger with minimal content retention and empirical feedback."""
from __future__ import annotations
import json
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()

class Store:
    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.db_path)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS preflight (
            request_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
            rule_version TEXT NOT NULL, verdict TEXT NOT NULL,
            prompt_sha256 TEXT NOT NULL, reference_sha256 TEXT NOT NULL,
            categories_json TEXT NOT NULL, findings_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS feedback (
            request_id TEXT NOT NULL, provider TEXT NOT NULL,
            outcome TEXT NOT NULL CHECK(outcome IN ('accepted','policy_rejected','technical_error')),
            created_at TEXT NOT NULL,
            PRIMARY KEY(request_id, provider),
            FOREIGN KEY(request_id) REFERENCES preflight(request_id)
        );
        """)
        self.db.commit()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def record(self, assessment: dict[str, Any], request_id: str | None = None) -> str:
        rid = request_id or str(uuid.uuid4())
        if not 1 <= len(rid) <= 128:
            raise ValueError("request_id length must be 1 to 128")
        with self.db:
            self.db.execute("INSERT INTO preflight VALUES (?,?,?,?,?,?,?,?)", (
                rid, timestamp(), assessment["rule_version"], assessment["verdict"],
                assessment["prompt_sha256"], str(assessment["reference_sha256"]),
                json.dumps(assessment["categories"]), json.dumps(assessment["findings"])))
        return rid

    def feedback(self, request_id: str, provider: str, outcome: str) -> None:
        if outcome not in ("accepted", "policy_rejected", "technical_error"):
            raise ValueError("invalid feedback outcome")
        if not provider or len(provider) > 100:
            raise ValueError("provider name must be 1 to 100 chars")
        with self.db:
            self.db.execute("INSERT INTO feedback VALUES (?,?,?,?)",
                            (request_id, provider, outcome, timestamp()))

    def stats(self, provider: str) -> dict[str, Any]:
        data = self.db.execute("""
            SELECT p.verdict, f.outcome, COUNT(*)
            FROM preflight p JOIN feedback f USING(request_id)
            WHERE f.provider=? GROUP BY p.verdict, f.outcome
        """, (provider,)).fetchall()
        grouped = {}
        for verdict, outcome, count in data:
            grouped.setdefault(verdict, {})[outcome] = count
        result = {"provider": provider, "note": "Observational outcomes, not a model of the provider's moderation system.", "by_verdict": {}}
        for verdict in ("PASS_LOCAL", "REVIEW", "BLOCK"):
            outcomes = grouped.get(verdict, {})
            accepted = outcomes.get("accepted", 0)
            rejected = outcomes.get("policy_rejected", 0)
            n = accepted + rejected
            entry: dict[str, Any] = {"accepted": accepted, "policy_rejected": rejected,
                                     "technical_error": outcomes.get("technical_error", 0),
                                     "samples": n, "acceptance_rate": None,
                                     "wilson_95_interval": None}
            if n >= 20:
                p = accepted / n
                z = 1.959963984540054
                den = 1 + z*z/n
                center = (p + z*z/(2*n))/den
                half = z * math.sqrt((p*(1-p)+z*z/(4*n))/n)/den
                entry["acceptance_rate"] = round(p, 4)
                entry["wilson_95_interval"] = [round(center-half, 4), round(center+half, 4)]
            result["by_verdict"][verdict] = entry
        return result
