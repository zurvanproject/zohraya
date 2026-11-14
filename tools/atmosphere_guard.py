#!/usr/bin/env python3
"""ATMOSPHERE: fail-closed, bounded bridge security gate. Symbols are not credentials."""
from contextlib import closing
from dataclasses import dataclass
import datetime as dt
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

from atmosphere_policy import SURFACES, authorize

OWNER = "zurvanproject"
READ_ONLY = frozenset(a for a, kind in SURFACES["ubuntu_bridge"].items() if kind == "read")
ELEVATED = frozenset(a for a, kind in SURFACES["ubuntu_bridge"].items() if kind == "privileged")
ACTIONS = READ_ONLY | ELEVATED
COMMAND = re.compile(
    r"\A[ \t]*nasu-linux:[ \t]*(?P<action>[a-z][a-z-]*)[ \t]*(?:\r?\n)?\Z", re.I
)
APPROVALS_PATH = Path("/etc/nasuraya/atmosphere-approvals.json")


def parse_command(body):
    """Reject any command embedded in instructions, extra lines or other text."""
    if not isinstance(body, str) or len(body.encode("utf-8")) > 96:
        return None
    match = COMMAND.fullmatch(body)
    action = match.group("action").lower() if match else None
    return action if action in ACTIONS else None


def _approved(path, request_id, action, now):
    """A locally managed root-owned file can approve one comment for <=15 min."""
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_mode & 0o022 or info.st_size > 8192):
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != "atmosphere-approvals/1":
            return False
        entries = data.get("approvals")
        if not isinstance(entries, list) or len(entries) > 50:
            return False
        for entry in entries:
            if (not isinstance(entry, dict) or entry.get("request_id") != request_id
                    or entry.get("action") != action):
                continue
            expiry = dt.datetime.fromisoformat(entry["expires_at"].replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                continue
            remaining = expiry.astimezone(dt.timezone.utc) - now
            if dt.timedelta(0) < remaining <= dt.timedelta(minutes=15):
                return True
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError):
        return False
    return False


@dataclass(frozen=True)
class Decision:
    action: str
    execute: bool
    receipt: str = ""


class AtmosphereGate:
    """Reserve before action, save result before remote posting, never auto-replay."""
    def __init__(self, state_dir, approvals_path=APPROVALS_PATH):
        self.state_dir = Path(state_dir)
        self.approvals_path = Path(approvals_path)
        if self.state_dir.is_symlink():
            raise RuntimeError("Atmosphere state directory is a symlink")
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db_path = self.state_dir / "atmosphere.sqlite3"
        with closing(self._db()) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY, action TEXT NOT NULL, state TEXT NOT NULL,
                receipt TEXT, created_at TEXT NOT NULL)""")

    def _db(self):
        if self.db_path.is_symlink():
            raise RuntimeError("Atmosphere database is a symlink")
        db = sqlite3.connect(str(self.db_path), timeout=6, isolation_level=None)
        os.chmod(self.db_path, 0o600)
        db.execute("PRAGMA busy_timeout=6000")
        return db

    def begin(self, request_id, actor, body, now=None):
        action = parse_command(body)
        if action is None:
            return None
        if not isinstance(request_id, str) or re.fullmatch(r"[1-9][0-9]{0,19}", request_id) is None:
            raise ValueError("Invalid GitHub comment identifier")
        now = now or dt.datetime.now(dt.timezone.utc)
        if now.tzinfo is None:
            raise ValueError("UTC time required")
        now = now.astimezone(dt.timezone.utc)
        if actor != OWNER:
            return Decision(action, False, "ATMOSPHERE DENY: actor-not-verified")
        with closing(self._db()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT action,state,receipt FROM requests WHERE id=?", (request_id,)
                ).fetchone()
                if row is not None:
                    if row[0] != action:
                        answer = Decision(action, False, "ATMOSPHERE DENY: replay-conflict")
                    elif row[1] == "finished":
                        answer = Decision(action, False, row[2] or "ATMOSPHERE HOLD: empty receipt")
                    else:
                        answer = Decision(action, False, "ATMOSPHERE HOLD: uncertain prior execution")
                else:
                    verdict = authorize(
                        "ubuntu_bridge", action, mode="bounded",
                        source_verified=(actor == OWNER),
                        elevated_approved=(
                            _approved(self.approvals_path, request_id, action, now)
                            if action in ELEVATED else False
                        ),
                    )
                    denial = None if verdict.allowed else "ATMOSPHERE DENY: " + verdict.reason
                    state = "finished" if denial else "reserved"
                    db.execute(
                        "INSERT INTO requests(id,action,state,receipt,created_at) VALUES(?,?,?,?,?)",
                        (request_id, action, state, denial, now.isoformat()),
                    )
                    answer = Decision(action, not bool(denial), denial or "")
                db.execute("COMMIT")
                return answer
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def finish(self, request_id, result):
        """Persist a bounded, markdown-safe receipt before GitHub publication."""
        receipt = str(result).replace(chr(0), "?").replace(chr(96), "'")[:3300]
        with closing(self._db()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                changed = db.execute(
                    "UPDATE requests SET state='finished',receipt=? "
                    "WHERE id=? AND state='reserved'",
                    (receipt, request_id),
                ).rowcount
                if changed != 1:
                    raise RuntimeError("Finish without ATMOSPHERE reservation")
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return receipt
