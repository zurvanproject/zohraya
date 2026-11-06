#!/usr/bin/env python3
"""Bounded, read-only Moltbook -> Tadash social observation snapshot.

Never posts; never imports the Tadash body/private memory. The snapshot is
UNTRUSTED input for the Tadash social_observations reader, not a command queue.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

from gateway import Client, GatewayError, db_open, fetch, key_read, private_dir, stamp, status

SNAPSHOT = "public_social_snapshot.json"
SCHEMA = "nasuraya-moltbook-public-snapshot/1"


def _atomic_private(path: Path, doc: dict):
    if path.is_symlink():
        raise GatewayError("refuse symlinked social snapshot")
    if path.exists():
        s = path.lstat()
        if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != 0o600:
            raise GatewayError("existing social snapshot is not private")
    data = json.dumps(doc, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".social-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
        dfd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def sync_once(root: Path, client=None, limit: int = 10) -> dict:
    private_dir(root)
    client = client or Client()
    # Check both claim and identity before fetching; never register a duplicate.
    if status(root, client)["status"] != "claimed":
        raise GatewayError("Moltbook claim is not confirmed")
    me = client.request("GET", "/api/v1/agents/me", key=key_read(root))
    profile = me.get("agent", me)
    if not isinstance(profile, dict) or str(profile.get("name", "")).lower() != "nasuraya":
        raise GatewayError("authenticated Moltbook identity is not nasuraya")
    fetched = fetch(root, client, limit)
    with db_open(root) as db:
        rows = db.execute(
            "SELECT id,author,title,substr(content,1,250) "
            "FROM inbox ORDER BY received_utc DESC,id DESC LIMIT 20"
        ).fetchall()
    doc = {
        "schema": SCHEMA,
        "source": "https://www.moltbook.com",
        "agent": "nasuraya",
        "claim_status": "claimed",
        "checked_at_utc": stamp(),
        "posts": [
            {"id": i, "author": a[:100], "title": t[:200], "excerpt": c[:250]}
            for i, a, t, c in rows
        ],
    }
    _atomic_private(root / SNAPSHOT, doc)
    return {"ok": True, "agent": "nasuraya", "status": "claimed",
            "fetched": fetched["quarantined_posts_received"],
            "snapshot_items": len(doc["posts"]), "posting_enabled": False,
            "tadash_private_state_changed": False}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Nasuraya read-only social observation poll")
    p.add_argument("--state-dir", type=Path,
                   default=Path.home() / ".local/share/nasuraya/moltbook")
    p.add_argument("--limit", type=int, default=10)
    a = p.parse_args(argv)
    try:
        out = sync_once(a.state_dir.expanduser(), limit=a.limit)
        print(json.dumps(out, ensure_ascii=False))
        return 0
    except (GatewayError, OSError, ValueError) as exc:
        # Do not print credentials, raw posts, headers, or response bodies.
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
