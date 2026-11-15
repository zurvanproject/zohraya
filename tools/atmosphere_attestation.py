"""ATMOSPHERE: offline signed-evidence gate and durable Awake delivery outbox.

No generated secret keys, network calls, model calls, code execution, or DIOS writes.
The operator must supply a trusted Ed25519 public key AND its *out-of-band* pin.
A valid signature attests a source commitment, never factual truth or authority.
"""
from __future__ import annotations
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import hmac
import json
import math
import os
import re
import sqlite3
import stat

SCHEMA = "atmosphere-evidence/2"
MANIFEST_SCHEMA = "atmosphere-evidence-manifest/1"
PAYLOAD_FIELDS = frozenset({"schema", "event_id", "topic", "source_ref", "observed_at", "sample_time",
                            "confidence", "value", "source_id", "source_revision"})
ENVELOPE_FIELDS = PAYLOAD_FIELDS | {"payload_sha256"}
COMMIT_FIELDS = frozenset({"event_id", "source_id", "source_revision", "payload_sha256"})
MANIFEST_FIELDS = frozenset({"schema", "issued_at", "expires_at", "commitments", "signature_ed25519"})
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
TOPIC = re.compile(r"[a-z][a-z0-9_.-]{2,63}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX128 = re.compile(r"[0-9a-f]{128}\Z")
UTC = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z\Z")


@dataclass(frozen=True)
class Decision:
    status: str
    reason: str
    authority: str = "none"
    establishes_truth: bool = False


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def utc(value):
    if not isinstance(value, str) or not UTC.fullmatch(value):
        raise ValueError("invalid-utc")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as e:
        raise ValueError("invalid-utc") from e


def time_now(now):
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("trusted-clock-required")
    return now.astimezone(timezone.utc)


def iso(now):
    return time_now(now).isoformat(timespec="seconds").replace("+00:00", "Z")


def payload_valid(item):
    if type(item) is not dict or set(item) != PAYLOAD_FIELDS or item["schema"] != SCHEMA:
        raise ValueError("payload-fields")
    for name in ("event_id", "source_id", "source_revision"):
        if not isinstance(item[name], str) or not TOKEN.fullmatch(item[name]):
            raise ValueError("invalid-" + name)
    if not isinstance(item["topic"], str) or not TOPIC.fullmatch(item["topic"]):
        raise ValueError("invalid-topic")
    if (not isinstance(item["source_ref"], str) or len(item["source_ref"]) > 240
            or not (item["source_ref"].startswith("https://github.com/zurvanproject/zohraya/commit/")
                    or re.fullmatch(r"tadash://[A-Za-z0-9._/-]{1,180}", item["source_ref"]))):
        raise ValueError("invalid-source-ref")
    if type(item["sample_time"]) not in (int, float) or not math.isfinite(item["sample_time"]) or not 0 <= item["sample_time"] <= 1e6:
        raise ValueError("invalid-sample-clock")
    if type(item["confidence"]) not in (int, float) or not math.isfinite(item["confidence"]) or not 0 <= item["confidence"] <= 1:
        raise ValueError("invalid-confidence")
    value = item["value"]
    if type(value) not in (bool, int, float, str):
        raise ValueError("invalid-value-type")
    if type(value) is float and not math.isfinite(value):
        raise ValueError("nonfinite-value")
    if type(value) is int and abs(value) > 10**12:
        raise ValueError("large-integer")
    if type(value) is str and (not 1 <= len(value) <= 120 or any(ord(c) < 32 for c in value)):
        raise ValueError("unsafe-value-string")
    utc(item["observed_at"])
    if len(canonical(item)) > 2200:
        raise ValueError("oversized-payload")


def envelope_for(row, *, source_id, source_revision):
    """Transform one *already extracted* DIOS/Stage3 scalar into an unsigned envelope.

    Callers must independently seal its digest, never trust the returned hash as a signature.
    """
    if type(row) is not dict or set(row) != {"event_id", "topic", "source_ref", "observed_at",
                                                     "sample_time", "confidence", "value"}:
        raise ValueError("unexpected-awake-row-contract")
    body = {**row, "schema": SCHEMA, "source_id": source_id, "source_revision": source_revision}
    payload_valid(body)
    return {**body, "payload_sha256": sha(canonical(body))}


def commitment(envelope):
    return {name: envelope[name] for name in COMMIT_FIELDS}


class PinnedRoot:
    """Verifier-only root; pin MUST come from trusted setup independent of documents/DB."""
    def __init__(self, public_key_hex, expected_key_sha256):
        if (not isinstance(public_key_hex, str) or not re.fullmatch(r"[0-9a-f]{64}", public_key_hex)
                or not isinstance(expected_key_sha256, str) or not HEX64.fullmatch(expected_key_sha256)):
            raise ValueError("invalid-root-key-or-pin")
        key = bytes.fromhex(public_key_hex)
        if not hmac.compare_digest(sha(key), expected_key_sha256):
            raise ValueError("root-pin-mismatch")
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        except ImportError as e:
            raise RuntimeError("ed25519-verifier-dependency-missing-fail-closed") from e
        self._key = Ed25519PublicKey.from_public_bytes(key)
        self.fingerprint = expected_key_sha256

    def verify(self, unsigned, signature_hex):
        if not isinstance(signature_hex, str) or not HEX128.fullmatch(signature_hex):
            return False
        try:
            from cryptography.exceptions import InvalidSignature
            self._key.verify(bytes.fromhex(signature_hex), canonical(unsigned))
            return True
        except InvalidSignature:
            return False


def check_manifest(manifest, root, now):
    now = time_now(now)
    if not isinstance(root, PinnedRoot) or type(manifest) is not dict or set(manifest) != MANIFEST_FIELDS:
        raise ValueError("manifest-shape")
    if manifest["schema"] != MANIFEST_SCHEMA:
        raise ValueError("manifest-schema")
    issued, expires = utc(manifest["issued_at"]), utc(manifest["expires_at"])
    if issued > now + timedelta(minutes=1) or expires < now or expires <= issued or expires-issued > timedelta(hours=48):
        raise ValueError("manifest-expired-or-time-window")
    commitments = manifest["commitments"]
    if not isinstance(commitments, list) or not 1 <= len(commitments) <= 50:
        raise ValueError("manifest-cardinality")
    checked = {}
    for c in commitments:
        if type(c) is not dict or set(c) != COMMIT_FIELDS:
            raise ValueError("commitment-shape")
        for field in ("event_id", "source_id", "source_revision"):
            if not isinstance(c[field], str) or not TOKEN.fullmatch(c[field]):
                raise ValueError("commitment-identity")
        if not isinstance(c["payload_sha256"], str) or not HEX64.fullmatch(c["payload_sha256"]):
            raise ValueError("commitment-hash")
        if c["event_id"] in checked:
            raise ValueError("duplicate-manifest-id")
        checked[c["event_id"]] = c
    unsigned = {k: v for k, v in manifest.items() if k != "signature_ed25519"}
    if not root.verify(unsigned, manifest["signature_ed25519"]):
        raise ValueError("invalid-signature")
    return checked


def checked_envelope(envelope, signatures, now):
    if type(envelope) is not dict or set(envelope) != ENVELOPE_FIELDS:
        raise ValueError("envelope-shape")
    body = {k: v for k, v in envelope.items() if k != "payload_sha256"}
    payload_valid(body)
    digest = envelope["payload_sha256"]
    if not isinstance(digest, str) or not HEX64.fullmatch(digest) or not hmac.compare_digest(digest, sha(canonical(body))):
        raise ValueError("self-hash-mismatch")
    entry = signatures.get(envelope["event_id"])
    if entry is None:
        raise ValueError("unattested-event")
    for field in COMMIT_FIELDS:
        if not hmac.compare_digest(str(entry[field]), str(envelope[field])):
            raise ValueError("signed-commitment-mismatch")
    age = time_now(now) - utc(envelope["observed_at"])
    if age < -timedelta(seconds=60) or age > timedelta(hours=24):
        raise ValueError("stale-or-future-evidence")
    return body


class EvidenceOutbox:
    """Durable one-way ingress. Source verification precedes *any* DB write."""
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError("db-symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(self._db()) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS events(
                id TEXT PRIMARY KEY, digest TEXT NOT NULL, body TEXT NOT NULL,
                root_fingerprint TEXT NOT NULL, signed_manifest_sha256 TEXT NOT NULL,
                signed_manifest TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','delivered')))""")

    def _db(self):
        if self.path.is_symlink():
            raise ValueError("db-symlink")
        db = sqlite3.connect(str(self.path), isolation_level=None, timeout=5)
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA synchronous=FULL")
        os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        return db

    def stage(self, envelopes, *, manifest, root, now):
        """Atomic bundle. Reject ALL if one scalar is not signed and fresh."""
        signed = check_manifest(manifest, root, now)
        if not isinstance(envelopes, list) or not 1 <= len(envelopes) <= 50:
            raise ValueError("bundle-cardinality")
        if len(envelopes) != len(signed):
            raise ValueError("bundle-manifest-size-mismatch")
        bodies, seen = [], set()
        for envelope in envelopes:
            body = checked_envelope(envelope, signed, now)
            if body["event_id"] in seen:
                raise ValueError("duplicate-bundle-id")
            seen.add(body["event_id"])
            bodies.append((envelope, body))
        sha_manifest = sha(canonical(manifest))
        with closing(self._db()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                added = duplicated = 0
                for env, body in bodies:
                    old = db.execute("SELECT digest,body FROM events WHERE id=?", (body["event_id"],)).fetchone()
                    if old is not None:
                        if not hmac.compare_digest(old[0], env["payload_sha256"]) or old[1] != canonical(body).decode():
                            raise ValueError("conflicting-event-replay")
                        duplicated += 1
                    else:
                        if count + added >= 2000:
                            raise ValueError("outbox-capacity")
                        db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?)",
                                   (body["event_id"], env["payload_sha256"], canonical(body).decode(),
                                    root.fingerprint, sha_manifest, canonical(manifest).decode(), "pending"))
                        added += 1
                db.execute("COMMIT")
                return {"status": "STAGED_FOR_REVIEW", "added": added, "duplicate": duplicated,
                        "authority": "none", "establishes_truth": False}
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def pending(self, *, root, now):
        """Recheck signed provenance after restart, before *every* Awake write."""
        with closing(self._db()) as db:
            rows = db.execute("SELECT id,digest,body,root_fingerprint,signed_manifest_sha256,signed_manifest FROM events WHERE state='pending' ORDER BY id").fetchall()
        records = []
        for event_id, digest, raw, pin, manifest_hash, manifest_raw in rows:
            body = json.loads(raw)
            payload_valid(body)
            if (not isinstance(root, PinnedRoot) or pin != root.fingerprint
                    or not hmac.compare_digest(sha(canonical(body)), digest)
                    or body["event_id"] != event_id):
                raise ValueError("outbox-local-integrity-failure")
            manifest = json.loads(manifest_raw)
            if not hmac.compare_digest(sha(canonical(manifest)), manifest_hash):
                raise ValueError("outbox-manifest-tamper")
            signatures = check_manifest(manifest, root, now)
            checked_envelope({**body, "payload_sha256": digest}, signatures, now)
            records.append(body)
        return records

    def delivered(self, ids):
        if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids):
            raise ValueError("invalid-delivery-ids")
        with closing(self._db()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                for item in ids:
                    changed = db.execute("UPDATE events SET state='delivered' WHERE id=? AND state='pending'", (item,)).rowcount
                    if changed != 1:
                        raise ValueError("not-pending-" + str(item))
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def stats(self):
        with closing(self._db()) as db:
            return {s: db.execute("SELECT COUNT(*) FROM events WHERE state=?", (s,)).fetchone()[0]
                    for s in ("pending", "delivered")}