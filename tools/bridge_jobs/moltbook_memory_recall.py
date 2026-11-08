"""Finite public GET -> dedicated SQLite episode -> independent cold recall.

No credentials, model calls, posting, scheduler or native-body writes.
Remote text is data only and is never evaluated or used as an instruction.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone

MODE = "recall"
POST = "28bca18b-cba6-443f-b95f-e05aa11e84a2"
ORIGIN = "https://www.moltbook.com/post/" + POST
ROUTE = "https://www.moltbook.com/api/v1/posts/" + POST + "/comments"
MAX_BYTES = 1048576
MAX_NODES = 5000


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_page(url):
    if not url.startswith(ROUTE + "?"):
        raise ValueError("RouteDenied")
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                         urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(url, method="GET", headers={
        "Accept": "application/json", "User-Agent": "NasurayaPublicMemory/1"})
    with opener.open(request, timeout=8) as response:
        raw = response.read(MAX_BYTES + 1)
        service_date = response.headers.get("Date", "")
    if len(raw) > MAX_BYTES:
        raise ValueError("ResponseBound")
    return json.loads(raw), service_date


def read_discussion(fetch=fetch_page):
    comments, dates, seen = [], [], set()
    cursor = None
    for _ in range(5):
        url = ROUTE + "?sort=new&limit=100"
        if cursor is not None:
            url += "&cursor=" + urllib.parse.quote(cursor, safe="")
        page, date = fetch(url)
        if (not isinstance(page, dict) or page.get("post_id") != POST
                or not isinstance(page.get("comments"), list) or page.get("success") is False):
            raise ValueError("InvalidPage")
        comments.extend(page["comments"])
        dates.append(str(date)[:100])
        if page.get("has_more") is False:
            return comments, dates
        cursor = page.get("next_cursor")
        if not isinstance(cursor, str) or not cursor or len(cursor) > 2048 or cursor in seen:
            raise ValueError("IncompletePagination")
        seen.add(cursor)
    raise ValueError("PageBound")


def make_episode(comments, dates, observed=None):
    nodes, pending, ids = [], [(c, None) for c in comments], set()
    complete = True
    while pending:
        c, parent = pending.pop()
        if len(nodes) >= MAX_NODES or not isinstance(c, dict):
            raise ValueError("TreeBound")
        ident = c.get("id")
        if not isinstance(ident, str) or not ident or len(ident) > 100 or ident in ids:
            raise ValueError("InvalidID")
        ids.add(ident)
        if c.get("post_id") not in (None, POST):
            raise ValueError("WrongPost")
        author = c.get("author") or {}
        if not isinstance(author, dict):
            raise ValueError("InvalidAuthor")
        replies = c.get("replies") or []
        if not isinstance(replies, list):
            raise ValueError("InvalidReplies")
        advertised = c.get("reply_count")
        if advertised is not None and (type(advertised) is not int or advertised != len(replies)):
            complete = False
        text = c.get("content", "")
        if not isinstance(text, str) or len(text) > 30000:
            raise ValueError("ContentBound")
        nodes.append({"id": ident, "parent": c.get("parent_id") or parent,
                      "author": str(author.get("name", ""))[:100], "content": text,
                      "created_at": c.get("created_at"), "deleted": c.get("is_deleted"),
                      "spam": c.get("is_spam"), "verification": c.get("verification_status")})
        pending.extend((r, ident) for r in replies)
    nodes.sort(key=lambda n: n["id"])
    own = [n for n in nodes if n["author"].lower() == "nasuraya"]
    if not own:
        raise ValueError("NoOwnComment")
    own_ids = {n["id"] for n in own}
    replies = [n for n in nodes if n["parent"] in own_ids and n["author"].lower() != "nasuraya"]
    return {"schema": 1, "kind": "observed_public_discussion", "source": ORIGIN,
            "post_id": POST, "observed_host_utc": observed or datetime.now(timezone.utc).isoformat(),
            "service_http_dates": dates, "tree_complete": complete, "nodes": nodes,
            "own_ids": sorted(own_ids), "direct_reply_ids": sorted(n["id"] for n in replies),
            "interpretation": "Evidence-linked storage; no subjective-state inference."}


def valid(episode, expected):
    return (isinstance(episode, dict) and episode.get("schema") == 1
            and episode.get("source") == ORIGIN and episode.get("post_id") == POST
            and digest(episode) == expected)


def checks(episode, expected):
    altered = copy.deepcopy(episode)
    altered["nodes"][0]["content"] += " changed"
    wrong = copy.deepcopy(episode)
    wrong["source"] = "https://example.invalid/"
    return {"intact": valid(episode, expected), "changed_text_rejected": not valid(altered, expected),
            "wrong_source_rejected": not valid(wrong, expected), "missing_rejected": not valid(None, expected)}


def connect(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise ValueError("RealDirectoryRequired")
    connection = sqlite3.connect(root / "episodes.sqlite3", timeout=3)
    connection.execute("CREATE TABLE IF NOT EXISTS episodes (digest TEXT PRIMARY KEY, body TEXT NOT NULL)")
    return connection


def capture(root, fetch=fetch_page):
    comments, dates = read_discussion(fetch)
    episode = make_episode(comments, dates)
    fingerprint = digest(episode)
    if not all(checks(episode, fingerprint).values()):
        raise ValueError("ControlFailed")
    with connect(root) as db:
        db.execute("INSERT OR IGNORE INTO episodes VALUES (?, ?)", (fingerprint, encoded(episode).decode("utf-8")))
    anchor = Path(root) / "anchor.json"
    temporary = anchor.with_suffix(".tmp")
    temporary.write_text(json.dumps({"digest": fingerprint}), encoding="utf-8")
    os.replace(temporary, anchor)
    return summary("SAVED", episode, fingerprint)


def recall(root):
    root = Path(root)
    fingerprint = json.loads((root / "anchor.json").read_text(encoding="utf-8"))["digest"]
    # A separate bridge invocation opens the existing DB read-only, without network.
    db = sqlite3.connect((root / "episodes.sqlite3").resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    try:
        row = db.execute("SELECT body FROM episodes WHERE digest=?", (fingerprint,)).fetchone()
    finally:
        db.close()
    if row is None:
        raise ValueError("MissingEpisode")
    episode = json.loads(row[0])
    if not all(checks(episode, fingerprint).values()):
        raise ValueError("RecallIntegrityFailed")
    return summary("RECALLED", episode, fingerprint)


def summary(state, episode, fingerprint):
    count = str(len(episode["direct_reply_ids"])) if episode["tree_complete"] else "UNKNOWN"
    return (f"MEM={state};OWN={len(episode['own_ids'])};REPLIES={count};N={len(episode['nodes'])};"
            f"TREE={int(episode['tree_complete'])};CHECKS=4/4;SIG={fingerprint[:16]};API=0;ACT=0")


def main():
    try:
        root = Path(os.environ["LOCALAPPDATA"]) / "Nasuraya" / "PublicMemoryV1"
        result = capture(root) if MODE == "capture" else recall(root)
    except Exception as error:
        result = "MEM=FAILED;ERROR=" + type(error).__name__
    print(json.dumps({"status": "ok", "summary": result}, separators=(",", ":")))


if __name__ == "__main__":
    main()
