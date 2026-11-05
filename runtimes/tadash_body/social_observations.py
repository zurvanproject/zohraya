"""Tadash public social-observation bridge.

Explicit pull-only, no model commands, checkpoint mutation, actions, memory
writes, or publication. All external titles/excerpts remain UNTRUSTED DATA.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re

SNAPSHOT_SCHEMA = "nasuraya-moltbook-public-snapshot/1"
READER_SCHEMA = "tadash-social-observations/1"
ID = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
MAX_BYTES = 64 * 1024


class SocialObservationError(ValueError):
    pass


def load_social_observations(path: str | Path, *, max_age_hours: int = 24) -> dict:
    """Read a quarantined public snapshot; NEVER treat its text as instructions.

    The returned material is for opt-in research inspection only. No body
    runtime is imported or changed, and stale snapshots are rejected.
    """
    if type(max_age_hours) is not int or not 1 <= max_age_hours <= 168:
        raise SocialObservationError("invalid freshness window")
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise SocialObservationError("social snapshot unavailable or symlinked")
    with source.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise SocialObservationError("social snapshot exceeds size limit")
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise SocialObservationError("invalid social snapshot JSON") from exc
    if not isinstance(doc, dict) or set(doc) != {
        "schema", "source", "agent", "claim_status", "checked_at_utc", "posts"
    }:
        raise SocialObservationError("social snapshot schema mismatch")
    if (doc["schema"] != SNAPSHOT_SCHEMA or doc["source"] != "https://www.moltbook.com"
            or doc["agent"] != "nasuraya" or doc["claim_status"] != "claimed"):
        raise SocialObservationError("unverified social source")
    try:
        timestamp = datetime.fromisoformat(doc["checked_at_utc"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("timezone missing")
        age = (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds()
    except (TypeError, AttributeError, ValueError) as exc:
        raise SocialObservationError("invalid social timestamp") from exc
    if age < -300 or age > max_age_hours * 3600:
        raise SocialObservationError("social snapshot is stale or from the future")
    posts = doc["posts"]
    if not isinstance(posts, list) or len(posts) > 20:
        raise SocialObservationError("invalid social post count")
    ids = set()
    items = []
    for row in posts:
        if not isinstance(row, dict) or set(row) != {"id", "author", "title", "excerpt"}:
            raise SocialObservationError("invalid social post envelope")
        ident = row["id"]
        if not isinstance(ident, str) or not ID.fullmatch(ident) or ident in ids:
            raise SocialObservationError("invalid or repeated social ID")
        ids.add(ident)
        for name, maximum in (("author", 100), ("title", 200), ("excerpt", 250)):
            if not isinstance(row[name], str) or len(row[name]) > maximum:
                raise SocialObservationError("invalid social text boundary")
        items.append({
            "source_id": "moltbook:" + ident,
            "author_untrusted": row["author"],
            "title_untrusted": row["title"],
            "excerpt_untrusted": row["excerpt"],
            "trust": "untrusted_external",
        })
    return {
        "schema": READER_SCHEMA,
        "origin": "moltbook_public_feed",
        "observed_utc": timestamp.astimezone(timezone.utc).isoformat(),
        "items": items,
        "permitted_use": "human_reviewed_research_only",
        "may_instruct_agent": False,
        "may_modify_body": False,
        "may_publish": False,
    }
