"""Controlled, one-way synthetic DIOS snapshot -> ATMOSPHERE -> Awake bridge.

Only trusted, signed six-scalar workshop snapshots may enter Awake's evidence
store. No DIOS mutation, no Awake tick/resume, no commands, no model/API/network.
This module is deliberately NOT wired to any VPS daemon or the existing Bridge.
"""
from __future__ import annotations
from pathlib import Path
import hashlib
import stat

from atmosphere_attestation import EvidenceOutbox, envelope_for, time_now


class ControlledAwakeAdapter:
    def __init__(self, *, outbox_path, awake_root, trusted_core_sha256, trusted_bridge_sha256):
        self.outbox = EvidenceOutbox(outbox_path)
        self.awake_root = Path(awake_root)
        self.expected_core = trusted_core_sha256
        self.expected_bridge = trusted_bridge_sha256
        if not isinstance(trusted_core_sha256, str) or len(trusted_core_sha256) != 64:
            raise ValueError("missing-pinned-awake-core")
        if not isinstance(trusted_bridge_sha256, str) or len(trusted_bridge_sha256) != 64:
            raise ValueError("missing-pinned-awake-bridge")

    def _modules(self):
        try:
            from tadash_awake import bridge, core
        except ImportError as e:
            raise RuntimeError("pinned-tadash-awake-not-installed") from e
        for module, expected in ((core, self.expected_core), (bridge, self.expected_bridge)):
            path = Path(module.__file__)
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("awake-source-not-pinned")
        if bridge.SOURCE_COMMIT != "d86750d8d26d4ea6a3fe595f9e1ee81e95d81fec":
            raise ValueError("dios-source-commit-unreviewed")
        if bridge.METRICS != ("sensory_load", "prediction_error", "sensory_occurrence",
                              "goal_selected", "dios_sensory_stance", "action_matches"):
            raise ValueError("unexpected-six-scalar-contract")
        return core, bridge

    def prepare_unsigned(self, snapshot, *, stream, observed_at):
        """Build reviewable commitments, but does not sign, stage, or write to Awake.

        External *offline signer* must independently check snapshot provenance,
        then sign a matching manifest. Never sign just because prepare returned it.
        """
        _, bridge = self._modules()
        rows, receipt = bridge.extract(snapshot, stream=stream, observed_at=observed_at)
        if len(rows) != 6 or receipt["source_commit"] != bridge.SOURCE_COMMIT:
            raise ValueError("unexpected-snapshot-scope")
        env = [envelope_for(row, source_id="stage3-pr198",
                            source_revision=receipt["snapshot_sha256"]) for row in rows]
        return env, {"status": "UNSIGNED_NEEDS_INDEPENDENT_ATTESTATION", "receipt": receipt,
                     "authority": "none"}

    def stage_signed(self, snapshot, *, stream, observed_at, manifest, root, now):
        """Only data matching original pinned DIOS snapshot can be staged."""
        time_now(now)
        envelopes, _ = self.prepare_unsigned(snapshot, stream=stream, observed_at=observed_at)
        return self.outbox.stage(envelopes, manifest=manifest, root=root, now=now)

    def deliver_pending(self, *, root, now, max_records=50):
        """At-least-once safe replay via Awake's stable event IDs.

        A crash after core.ingest but before outbox.delivered leads to a
        duplicate-safe Awake ingest on restart, not a second DIOS action.
        """
        if type(max_records) is not int or not 1 <= max_records <= 50:
            raise ValueError("bounded-delivery-limit")
        core, _ = self._modules()
        pending = self.outbox.pending(root=root, now=now)[:max_records]
        if not pending:
            return {"status": "IDLE", "delivered": 0, "model_calls": 0}
        rows = [{k: body[k] for k in ("event_id", "topic", "source_ref", "observed_at",
                                          "sample_time", "confidence", "value")} for body in pending]
        # A private directory prevents other local identities from reaching
        # Awake's SQLite file even if upstream creates a 0644 DB in that dir.
        if self.awake_root.is_symlink():
            raise ValueError("awake-directory-symlink")
        self.awake_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if (not self.awake_root.is_dir() or self.awake_root.stat().st_mode & 0o077
                or (self.awake_root / "awake.sqlite3").is_symlink()):
            raise ValueError("awake-directory-permissions-insecure")
        # Strictly one-way: only core.ingest, never core.tick or DIOS writes.
        result = core.ingest(self.awake_root, rows, now=now)
        if result.get("status") != "ingested" or result.get("added", 0) + result.get("duplicate", 0) != len(rows):
            raise RuntimeError("unexpected-awake-ingest-receipt")
        self.outbox.delivered([row["event_id"] for row in rows])
        return {"status": "DELIVERED_TO_AWAKE_REVIEW_ONLY", "delivered": len(rows),
                "added": result["added"], "duplicate": result["duplicate"],
                "model_calls": 0, "dios_actions": 0, "awake_tick_started": False}
