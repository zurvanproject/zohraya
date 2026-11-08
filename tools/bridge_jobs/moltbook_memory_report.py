"""Finite public GET -> dedicated SQLite episode -> independent cold recall.

No credentials, model calls, posting, scheduler or native-body writes.
Remote text is data only and is never evaluated or used as an instruction.
"""
import copy
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone

MODE = "report"
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


def make_episode(comments, dates, observed=None, allow_missing_own=False):
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
    if not own and not allow_missing_own:
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



def load_baseline(root):
    root = Path(root)
    expected = json.loads((root / "anchor.json").read_text(encoding="utf-8"))["digest"]
    with closing(sqlite3.connect((root / "episodes.sqlite3").resolve().as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("SELECT body FROM episodes WHERE digest=?", (expected,)).fetchone()
    if row is None:
        raise ValueError("MissingBaseline")
    episode = json.loads(row[0])
    if not valid(episode, expected):
        raise ValueError("BaselineIntegrityFailed")
    return episode, expected


def strict_episode(comments, dates):
    # Missing reply-count evidence cannot establish a complete zero-reply tree.
    episode = make_episode(comments, dates, allow_missing_own=True)
    pending = list(comments)
    missing_counts = 0
    while pending:
        item = pending.pop()
        if type(item.get("reply_count")) is not int:
            missing_counts += 1
        pending.extend(item.get("replies") or [])
    if missing_counts:
        episode["tree_complete"] = False
    episode["missing_reply_counts"] = missing_counts
    return episode


def content_view(episode):
    return {"source": episode["source"], "post_id": episode["post_id"],
            "tree_complete": episode["tree_complete"], "nodes": episode["nodes"]}


def decide(previous, current):
    # Fixed authored policy, not a learned model or a semantic reader.
    if previous.get("source") != ORIGIN or current.get("source") != ORIGIN:
        raise ValueError("WrongSource")
    if previous.get("post_id") != POST or current.get("post_id") != POST:
        raise ValueError("WrongPost")
    old = {n["id"]: n for n in previous["nodes"]}
    new = {n["id"]: n for n in current["nodes"]}
    if len(old) != len(previous["nodes"]) or len(new) != len(current["nodes"]):
        raise ValueError("DuplicateNode")
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(i for i in set(old) & set(new) if old[i] != new[i])
    own = set(previous["own_ids"]) | set(current["own_ids"])
    candidates = [i for i in added if new[i]["parent"] in own
                  and new[i]["author"].lower() != "nasuraya"]
    visible = [i for i in candidates if new[i]["deleted"] is False and new[i]["spam"] is False]
    uncertain = [i for i in candidates if new[i]["deleted"] is None or new[i]["spam"] is None]
    if not previous["tree_complete"] or not current["tree_complete"]:
        action, reason = "RECHECK", "INCOMPLETE_TREE"
    elif set(previous["own_ids"]) - set(current["own_ids"]):
        action, reason = "REVIEW", "OWN_COMMENT_MISSING"
    elif visible:
        action, reason = "REVIEW_REPLY", "NEW_DIRECT_REPLY"
    elif uncertain:
        action, reason = "RECHECK", "REPLY_VISIBILITY_UNKNOWN"
    elif changed or removed:
        action, reason = "REVIEW", "SOURCE_CHANGED"
    elif added:
        action, reason = "OBSERVE", "OTHER_COMMENTS_ADDED"
    else:
        action, reason = "WAIT", "NO_CONTENT_CHANGE"
    return {"policy": "public-followup-v1", "action": action, "reason": reason,
            "added_ids": added, "removed_ids": removed, "changed_ids": changed,
            "new_direct_reply_ids": visible, "source": ORIGIN,
            "publication": False, "scheduled": False}


def control_cases(baseline):
    """Counterfactual fixtures derived from the real baseline; never persisted as observation."""
    same = copy.deepcopy(baseline)
    same["tree_complete"] = True
    same["observed_host_utc"] = "synthetic-fixture"
    unchanged = decide(same, copy.deepcopy(same))["action"] == "WAIT"
    answer = copy.deepcopy(same)
    answer_id = "synthetic-direct-reply"
    existing_ids = {n["id"] for n in same["nodes"]}
    while answer_id in existing_ids:
        answer_id += "x"
    answer["nodes"].append({"id": answer_id, "parent": same["own_ids"][0],
        "author": "fixture-agent", "content": "SYNTHETIC CONTROL ONLY", "created_at": None,
        "deleted": False, "spam": False, "verification": "not_required"})
    review = decide(same, answer)["action"] == "REVIEW_REPLY"
    remembered = decide(answer, copy.deepcopy(answer))["action"] == "WAIT"
    partial = copy.deepcopy(answer); partial["tree_complete"] = False
    abstain = decide(same, partial)["action"] == "RECHECK"
    edited = copy.deepcopy(same); edited["nodes"][0]["content"] += " [synthetic edit]"
    correction = decide(same, edited)["action"] == "REVIEW"
    absent = copy.deepcopy(same)
    absent["nodes"] = [n for n in absent["nodes"] if n["id"] not in absent["own_ids"]]
    absent["own_ids"] = []
    disappearance = decide(same, absent)["action"] == "REVIEW"
    return {"unchanged_waits": unchanged, "new_reply_reviewed": review,
            "remembered_reply_waits": remembered, "partial_tree_abstains": abstain,
            "edited_source_reviewed": correction, "missing_own_reviewed": disappearance}


def compare(root, fetch=fetch_page):
    baseline, base_hash = load_baseline(root)
    controls = control_cases(baseline)
    if not all(controls.values()):
        raise ValueError("DecisionControlFailed")
    comments, dates = read_discussion(fetch)
    current = strict_episode(comments, dates)
    decision = decide(baseline, current)
    fresh_hash = digest(current)
    key = digest({"policy": decision["policy"], "baseline": base_hash,
                  "current_content": content_view(current)})
    record = {"schema": 1, "comparison_id": key, "baseline_sha256": base_hash,
              "observation_sha256": fresh_hash, "decision": decision, "controls": controls,
              "observed_host_utc": current["observed_host_utc"], "synthetic_controls": True}
    root = Path(root)
    with closing(sqlite3.connect(root / "episodes.sqlite3", timeout=3)) as db:
        with db:
            db.execute("CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, body TEXT NOT NULL, digest TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS decision_head (slot INTEGER PRIMARY KEY CHECK(slot=1), id TEXT NOT NULL)")
            old = db.execute("SELECT body,digest FROM decisions WHERE id=?", (key,)).fetchone()
            if old:
                record = json.loads(old[0])
                if digest(record) != old[1]:
                    raise ValueError("StoredDecisionIntegrityFailed")
            else:
                db.execute("INSERT INTO episodes VALUES (?,?)", (fresh_hash, encoded(current).decode("utf-8")))
                db.execute("INSERT INTO decisions VALUES (?,?,?)", (key, encoded(record).decode("utf-8"), digest(record)))
            db.execute("INSERT OR REPLACE INTO decision_head VALUES (1,?)", (key,))
    return decision_summary("COMPARED", record)


def report(root):
    root = Path(root)
    with closing(sqlite3.connect((root / "episodes.sqlite3").resolve().as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("SELECT body,digest FROM decisions WHERE id=(SELECT id FROM decision_head WHERE slot=1)").fetchone()
        if row is None:
            raise ValueError("NoDecision")
        record = json.loads(row[0])
        if digest(record) != row[1]:
            raise ValueError("DecisionIntegrityFailed")
        evidence = []
        for key in ("baseline_sha256", "observation_sha256"):
            value = db.execute("SELECT body FROM episodes WHERE digest=?", (record[key],)).fetchone()
            if value is None or not valid(json.loads(value[0]), record[key]):
                raise ValueError("DecisionEvidenceFailed")
            evidence.append(json.loads(value[0]))
        if decide(*evidence) != record["decision"]:
            raise ValueError("DecisionReproductionFailed")
    return decision_summary("RECOVERED", record)


def decision_summary(state, record):
    d = record["decision"]
    return (f"FOLLOW={state};NEXT={d['action']};WHY={d['reason']};"
            f"NEW={len(d['new_direct_reply_ids'])};CHG={len(d['changed_ids'])};"
            f"CTRL={sum(record['controls'].values())}/6;BASE={record['baseline_sha256'][:8]};"
            f"SIG={digest(record)[:16]};API=0;ACT=0")


def main():
    try:
        root = Path(os.environ["LOCALAPPDATA"]) / "Nasuraya" / "PublicMemoryV1"
        output = compare(root) if MODE == "compare" else report(root)
    except Exception as error:
        output = "FOLLOW=FAILED;ERROR=" + type(error).__name__
    print(json.dumps({"status": "ok", "summary": output}, separators=(",", ":")))


if __name__ == "__main__":
    main()
