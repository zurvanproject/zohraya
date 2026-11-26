"""Private, bounded Gmail-feedback staging. No network, model, mail or execution actions.

Email is evidence supplied by a third party, never a user instruction. Reviewed
references remain distinct from implemented or runtime-verified project changes.
"""
import argparse
import copy
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from pathlib import Path

SCHEMA = "nasuraya-email-feedback/1"
MAX_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 2000
MAX_REVIEWS = 4000
REVIEW_OUTCOMES = {"reference_supported", "unsupported", "rejected", "superseded"}
CLASSES = {"excluded_sent", "pending_correlation", "pending_review", "candidate",
           "operational_ack", "operational_bounce", "irrelevant"}
CORRELATIONS = {"root", "linked", "missing_reference", "conflicting_reference"}


def canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canon(value).encode("utf-8")).hexdigest()


def stamp(value=None):
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def text(value, limit, label):
    if not isinstance(value, str) or not 1 <= len(value) <= limit or any(ord(c) < 32 for c in value):
        raise ValueError("invalid " + label)
    return value


def address(value):
    value = text(value, 254, "mailbox").strip().lower()
    if not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+", value):
        raise ValueError("invalid mailbox")
    return value


def ident(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("invalid provider id")
    return value


def rfc_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"<[^\s<>]{1,250}>", value):
        raise ValueError("invalid RFC message id")
    return value


def initialize(config):
    if not isinstance(config, dict) or set(config) != {"mailbox", "roots"}:
        raise ValueError("invalid config fields")
    if not isinstance(config["roots"], list) or not 1 <= len(config["roots"]) <= 20:
        raise ValueError("expected 1..20 roots")
    normalized = {"mailbox": address(config["mailbox"]), "roots": []}
    for root in config["roots"]:
        if not isinstance(root, dict) or set(root) != {"thread_id", "message_id", "rfc_message_id", "recipient"}:
            raise ValueError("invalid root fields")
        normalized["roots"].append({"thread_id": ident(root["thread_id"]),
                                   "message_id": ident(root["message_id"]),
                                   "rfc_message_id": rfc_id(root["rfc_message_id"]),
                                   "recipient": address(root["recipient"])})
    for field in ("thread_id", "message_id", "rfc_message_id"):
        if len({r[field] for r in normalized["roots"]}) != len(normalized["roots"]):
            raise ValueError("duplicate root " + field)
    return {"schema": SCHEMA, "revision": 0, "config": normalized,
            "records": {}, "candidates": {}, "review_events": []}


def validate_state(state):
    if not isinstance(state, dict) or set(state) != {"schema", "revision", "config", "records", "candidates", "review_events"}:
        raise ValueError("invalid state fields")
    if state["schema"] != SCHEMA or type(state["revision"]) is not int or state["revision"] < 0:
        raise ValueError("invalid schema or revision")
    if initialize(state["config"])["config"] != state["config"]:
        raise ValueError("config not canonical")
    if not isinstance(state["records"], dict) or len(state["records"]) > MAX_RECORDS:
        raise ValueError("invalid records")
    if not isinstance(state["candidates"], dict) or len(state["candidates"]) > MAX_RECORDS * 5:
        raise ValueError("invalid candidates")
    if not isinstance(state["review_events"], list) or len(state["review_events"]) > MAX_REVIEWS:
        raise ValueError("invalid review events")
    roots = {r["thread_id"]: r for r in state["config"]["roots"]}
    for key, record in state["records"].items():
        fields = {"message_id", "thread_id", "rfc_message_id", "root_message_id", "received_at", "processed_at",
                  "updated_at", "sender_address", "attribution_status", "correlation", "classification",
                  "payload_sha256", "summary", "summary_provenance", "candidate_ids", "classification_history"}
        if not isinstance(record, dict) or set(record) != fields or record["thread_id"] not in roots:
            raise ValueError("invalid record fields")
        if key != digest([state["config"]["mailbox"], ident(record["message_id"])]) or record["root_message_id"] != roots[record["thread_id"]]["message_id"]:
            raise ValueError("invalid record identity")
        address(record["sender_address"])
        if record["rfc_message_id"] is not None:
            rfc_id(record["rfc_message_id"])
        if record["classification"] not in CLASSES or record["correlation"] not in CORRELATIONS or record["attribution_status"] not in {"address_match_only", "pending_attribution"}:
            raise ValueError("invalid record status")
        if record["summary_provenance"] != "agent_inference" or not re.fullmatch(r"[a-f0-9]{64}", record["payload_sha256"]):
            raise ValueError("invalid record provenance")
        for field in ("received_at", "processed_at", "updated_at"):
            if stamp(record[field]) != record[field]:
                raise ValueError("noncanonical record timestamp")
        if record["summary"]:
            text(record["summary"], 1200, "record summary")
        ids = record["candidate_ids"]
        if not isinstance(ids, list) or len(ids) > 5 or len(set(ids)) != len(ids) or any(c not in state["candidates"] for c in ids):
            raise ValueError("invalid candidate links")
        if bool(ids) != (record["classification"] == "candidate"):
            raise ValueError("candidate classification mismatch")
        history = record["classification_history"]
        if not isinstance(history, list) or not 1 <= len(history) <= 20:
            raise ValueError("invalid classification history")
        for event in history:
            if not isinstance(event, dict) or set(event) != {"classification", "correlation", "recorded_at", "summary_sha256"} or event["classification"] not in CLASSES or event["correlation"] not in CORRELATIONS:
                raise ValueError("invalid classification event")
            if stamp(event["recorded_at"]) != event["recorded_at"] or not re.fullmatch(r"[a-f0-9]{64}", event["summary_sha256"]):
                raise ValueError("invalid classification event value")
        if history[-1] != {"classification": record["classification"], "correlation": record["correlation"], "recorded_at": record["updated_at"], "summary_sha256": digest(record["summary"])} or history[0]["recorded_at"] != record["processed_at"]:
            raise ValueError("classification projection mismatch")
    seen = {}
    for event in state["review_events"]:
        fields = {"event_id", "candidate_id", "outcome", "source_refs", "reason", "recorded_at", "supersedes", "provenance", "runtime_effect_verified"}
        if not isinstance(event, dict) or set(event) != fields or event["candidate_id"] not in state["candidates"] or event["outcome"] not in REVIEW_OUTCOMES:
            raise ValueError("invalid review event")
        if event["event_id"] != "review-" + digest({k: v for k, v in event.items() if k != "event_id"})[:40] or event["event_id"] in seen:
            raise ValueError("review event integrity mismatch")
        if event["provenance"] != "runtime_review" or event["runtime_effect_verified"] is not False:
            raise ValueError("invalid review authority")
        if not isinstance(event["source_refs"], list) or len(event["source_refs"]) > 10 or (event["outcome"] == "reference_supported" and not event["source_refs"]):
            raise ValueError("invalid review sources")
        for ref in event["source_refs"]:
            text(ref, 500, "source ref")
        text(event["reason"], 1200, "review reason")
        stamp(event["recorded_at"])
        if not isinstance(event["supersedes"], list) or len(event["supersedes"]) > 10 or any(x not in seen or seen[x]["candidate_id"] != event["candidate_id"] or seen[x]["outcome"] == "superseded" for x in event["supersedes"]) or (event["outcome"] == "superseded" and not event["supersedes"]):
            raise ValueError("invalid review lineage")
        seen[event["event_id"]] = event
    for cid, candidate in state["candidates"].items():
        if not isinstance(candidate, dict) or set(candidate) != {"record_key", "claim", "provenance", "evidence_status", "review_status", "active_review_id"} or candidate["record_key"] not in state["records"]:
            raise ValueError("invalid candidate fields")
        record = state["records"][candidate["record_key"]]
        if cid not in record["candidate_ids"] or candidate["provenance"] != "agent_inference" or candidate["evidence_status"] != "unverified_email_proposal":
            raise ValueError("invalid candidate provenance")
        text(candidate["claim"], 400, "claim")
        events = [e for e in state["review_events"] if e["candidate_id"] == cid]
        removed = {x for e in events for x in e["supersedes"]}
        active = [e for e in events if e["event_id"] not in removed and e["outcome"] != "superseded"]
        if candidate["review_status"] != (active[-1]["outcome"] if active else "unreviewed") or candidate["active_review_id"] != (active[-1]["event_id"] if active else None):
            raise ValueError("candidate review projection mismatch")
    if len(canon(state).encode("utf-8")) > MAX_BYTES:
        raise ValueError("state capacity reached")
    return state


def normalize_message(message):
    if not isinstance(message, dict) or len(canon(message).encode("utf-8")) > MAX_BYTES:
        raise ValueError("invalid or oversized message")
    mid, thread = ident(message.get("id")), ident(message.get("thread_id"))
    payload = message.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("full Gmail message required")
    headers = {}
    for h in payload.get("headers", []):
        if not isinstance(h, dict) or not isinstance(h.get("name"), str) or not isinstance(h.get("value"), str):
            raise ValueError("invalid header")
        name = h["name"].lower()
        if name in {"from", "message-id", "in-reply-to", "references", "auto-submitted", "subject", "content-type"}:
            if name in headers:
                raise ValueError("ambiguous " + name + " header")
            headers[name] = h["value"]
    sender = address(parseaddr(headers.get("from", ""))[1])
    rfc = rfc_id(headers["message-id"]) if headers.get("message-id") else None
    received = message.get("internal_date")
    if not isinstance(received, (str, int)) or not re.fullmatch(r"\d{1,14}", str(received)):
        raise ValueError("Gmail internal_date required")
    received = stamp(datetime.fromtimestamp(int(received) / 1000, timezone.utc))
    labels = message.get("label_ids", [])
    if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
        raise ValueError("invalid labels")

    def content(part, depth=0):
        if depth > 20 or not isinstance(part, dict):
            raise ValueError("invalid MIME tree")
        body = part.get("body") or {}
        if not isinstance(body, dict):
            raise ValueError("invalid MIME body")
        return {"mime_type": part.get("mime_type"), "filename": part.get("filename"),
                "size": body.get("size"), "content": body.get("content"),
                "base64_url_content": body.get("base64_url_content"),
                "parts": [content(p, depth + 1) for p in part.get("parts") or []]}

    fingerprint = digest({"id": mid, "thread": thread, "headers": headers,
                          "received": received, "content": content(payload)})
    return mid, thread, headers, sender, rfc, received, labels, fingerprint


def validate_review(review):
    if review is None:
        return {"kind": "needs_review", "summary": "", "claims": []}
    if not isinstance(review, dict) or set(review) - {"kind", "summary", "claims", "reason"}:
        raise ValueError("invalid review fields")
    claims = review.get("claims", [])
    if not isinstance(claims, list) or len(claims) > 5:
        raise ValueError("expected at most five claims")
    kind = review.get("kind", "substantive" if claims else "needs_review")
    if kind not in {"substantive", "acknowledgment", "delivery_failure", "irrelevant", "needs_review"}:
        raise ValueError("invalid review kind")
    if kind != "substantive" and claims:
        raise ValueError("non-substantive review has claims")
    summary = review.get("summary", "")
    if summary:
        text(summary, 1200, "review summary")
    if kind == "substantive" and (not summary or not claims):
        raise ValueError("substantive review requires summary and claims")
    if review.get("reason"):
        text(review["reason"], 400, "review reason")
    return {"kind": kind, "summary": summary,
            "claims": [text(c, 400, "claim") for c in claims], "reason": review.get("reason", "")}


def process(state, mailbox, message, review=None, now=None):
    """Return a new ledger and receipt. Review is operator analysis, never email authority."""
    validate_state(state)
    at = stamp(now)
    if address(mailbox) != state["config"]["mailbox"]:
        raise ValueError("mailbox outside configured scope")
    mid, thread, headers, sender, rfc, received, labels, fingerprint = normalize_message(message)
    if datetime.fromisoformat(received.replace("Z", "+00:00")) > datetime.fromisoformat(at.replace("Z", "+00:00")) + timedelta(minutes=5):
        raise ValueError("future message")
    root = next((r for r in state["config"]["roots"] if r["thread_id"] == thread), None)
    if root is None:
        return state, {"status": "ignored_out_of_scope", "duplicate": False, "record_key": None}
    key = digest([state["config"]["mailbox"], mid])
    old = state["records"].get(key)
    if old is not None:
        if old["payload_sha256"] != fingerprint:
            raise ValueError("message id reused with changed content")
        retryable = old["classification"] in {"pending_review", "pending_correlation"}
        corrected_operational = (old["classification"] in {"operational_ack", "operational_bounce"}
                                 and isinstance(review, dict) and review.get("kind") == "substantive")
        if not (retryable or corrected_operational) or old["candidate_ids"]:
            return state, {"status": old["classification"], "duplicate": True, "record_key": key}
    if old is None and len(state["records"]) >= MAX_RECORDS:
        raise ValueError("record capacity reached")
    analysis = validate_review(review)
    known_refs = {root["rfc_message_id"]}
    known_refs.update(r["rfc_message_id"] for r in state["records"].values()
                      if r["thread_id"] == thread and r["correlation"] == "linked" and r["rfc_message_id"])
    ref_headers = headers.get("references", "") + " " + headers.get("in-reply-to", "")
    refs = set(re.findall(r"<[^\s<>]+>", ref_headers))
    correlation = "linked" if refs & known_refs else "missing_reference" if not refs else "conflicting_reference"
    attribution = "address_match_only" if sender == root["recipient"] else "pending_attribution"
    if mid == root["message_id"] or "SENT" in labels or sender == state["config"]["mailbox"]:
        classification, correlation = "excluded_sent", "root" if mid == root["message_id"] else correlation
    elif correlation != "linked":
        classification = "pending_correlation"
    else:
        # Automatic/report headers are transport hints, not semantic verdicts.
        # Only the operator's analysis can distinguish useful feedback, an ack,
        # or a delivery failure. Nothing in the email grants that authority.
        classification = {"substantive": "candidate", "acknowledgment": "operational_ack",
                          "delivery_failure": "operational_bounce", "irrelevant": "irrelevant",
                          "needs_review": "pending_review"}[analysis["kind"]]
    record = {"message_id": mid, "thread_id": thread, "rfc_message_id": rfc,
              "root_message_id": root["message_id"], "received_at": received,
              "processed_at": old["processed_at"] if old else at, "updated_at": at,
              "sender_address": sender, "attribution_status": attribution,
              "correlation": correlation, "classification": classification,
              "payload_sha256": fingerprint, "summary": "", "summary_provenance": "agent_inference",
              "candidate_ids": [], "classification_history": copy.deepcopy(old["classification_history"]) if old else []}
    if classification in {"candidate", "operational_ack", "operational_bounce", "irrelevant", "pending_review"}:
        record["summary"] = analysis["summary"]
    if old is not None and all(record[k] == old[k] for k in ("classification", "correlation", "summary")):
        return state, {"status": old["classification"], "duplicate": True, "record_key": key}
    if len(record["classification_history"]) >= 20:
        raise ValueError("classification transition capacity reached")
    record["classification_history"].append({"classification": classification, "correlation": correlation,
                                              "recorded_at": at, "summary_sha256": digest(record["summary"])})
    result = copy.deepcopy(state)
    if classification == "candidate":
        for i, claim in enumerate(analysis["claims"]):
            cid = "email-" + key[:32] + "-" + str(i)
            result["candidates"][cid] = {"record_key": key, "claim": claim,
                                         "provenance": "agent_inference", "evidence_status": "unverified_email_proposal",
                                         "review_status": "unreviewed", "active_review_id": None}
            record["candidate_ids"].append(cid)
    result["records"][key] = record
    result["revision"] += 1
    validate_state(result)
    return result, {"status": classification, "duplicate": old is not None,
                    "analysis_applied": True, "record_key": key}


def record_review(state, candidate_id, outcome, source_refs, reason, now=None, supersedes=None):
    """Append an analyst review; never grants execution authority or runtime verification."""
    validate_state(state)
    if candidate_id not in state["candidates"] or outcome not in REVIEW_OUTCOMES:
        raise ValueError("unknown candidate or review outcome")
    if not isinstance(source_refs, list) or len(source_refs) > 10:
        raise ValueError("invalid source refs")
    refs = [text(v, 500, "source ref") for v in source_refs]
    if outcome == "reference_supported" and not refs:
        raise ValueError("reference-supported review requires source refs")
    prior = {e["event_id"]: e for e in state["review_events"]}
    supersedes = [] if supersedes is None else supersedes
    if not isinstance(supersedes, list) or len(supersedes) > 10 or any(
            x not in prior or prior[x]["candidate_id"] != candidate_id or prior[x]["outcome"] == "superseded" for x in supersedes):
        raise ValueError("invalid superseded reviews")
    if outcome == "superseded" and not supersedes:
        raise ValueError("superseding review requires target")
    event = {"candidate_id": candidate_id, "outcome": outcome, "source_refs": refs,
             "reason": text(reason, 1200, "review reason"), "recorded_at": stamp(now),
             "supersedes": supersedes, "provenance": "runtime_review",
             "runtime_effect_verified": False}
    event["event_id"] = "review-" + digest(event)[:40]
    if event["event_id"] in prior:
        return state
    if len(prior) >= MAX_REVIEWS:
        raise ValueError("review capacity reached")
    result = copy.deepcopy(state)
    result["review_events"].append(event)
    events = [e for e in result["review_events"] if e["candidate_id"] == candidate_id]
    removed = {x for e in events for x in e["supersedes"]}
    active = [e for e in events if e["event_id"] not in removed and e["outcome"] != "superseded"]
    candidate = result["candidates"][candidate_id]
    candidate["review_status"] = active[-1]["outcome"] if active else "unreviewed"
    candidate["active_review_id"] = active[-1]["event_id"] if active else None
    result["revision"] += 1
    return validate_state(result)


def awake_event(state, record_key):
    validate_state(state)
    record = state["records"][record_key]
    # A local adapter status, not a confidence claim about the email's assertions.
    return {"event_id": "email-feedback:" + record_key + ":" + str(len(record["classification_history"]) - 1),
            "topic": "email_feedback." + record_key[:32], "source_ref": "tadash://email-feedback/" + record_key,
            "observed_at": record["updated_at"], "value": record["classification"], "confidence": 1.0}


def export_awake(state, record_key, root, now=None):
    from tadash_awake.core import ingest
    return ingest(root, [awake_event(state, record_key)], now=now)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def load_json(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("symlink input refused")
    with path.open("rb") as f:
        raw = f.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("JSON input too large")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


@contextmanager
def file_lock(path):
    """Kernel-owned, nonblocking lock; process exit releases it. Keep its inode."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError("symlink lock refused")
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        yield
    finally:
        try:
            if acquired:
                if os.name == "nt":
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def atomic_save(path, state, expected_revision):
    """Local CAS + kernel lock. Library callers additionally need its version guard."""
    validate_state(state)
    if type(expected_revision) is not int:
        raise ValueError("expected_revision is required")
    path = Path(path)
    if path.is_symlink():
        raise ValueError("symlink output refused")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    with file_lock(lock):
        temporary = None
        try:
            old = validate_state(load_json(path)) if path.exists() else None
            revision = old["revision"] if old is not None else -1
            if revision != expected_revision:
                raise ValueError("revision conflict")
            if old is not None and canon(state) == canon(old):
                return
            if state["revision"] != revision + 1:
                raise ValueError("revision must advance exactly once")
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                             prefix=path.name + ".", suffix=".tmp", delete=False) as f:
                temporary = Path(f.name)
                os.chmod(f.name, 0o600)
                f.write(canon(state) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)
            temporary = None
            if hasattr(os, "O_DIRECTORY"):
                dfd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--config", required=True)
    init.add_argument("--state", required=True)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--state", required=True)
    ingest.add_argument("--message", required=True)
    ingest.add_argument("--mailbox", required=True)
    ingest.add_argument("--review")
    ingest.add_argument("--expected-revision", type=int, required=True)
    assess = sub.add_parser("review")
    assess.add_argument("--state", required=True)
    assess.add_argument("--assessment", required=True)
    assess.add_argument("--expected-revision", type=int, required=True)
    export = sub.add_parser("export-awake")
    export.add_argument("--state", required=True)
    export.add_argument("--record-key", required=True)
    export.add_argument("--awake-root", required=True)
    args = parser.parse_args(argv)
    if args.command == "init":
        state = initialize(load_json(args.config))
        atomic_save(args.state, state, -1)
        result = {"status": "initialized", "revision": 0}
    else:
        state = validate_state(load_json(args.state))
        if args.command == "export-awake":
            result = export_awake(state, args.record_key, args.awake_root)
        elif args.command == "ingest":
            updated, result = process(state, args.mailbox, load_json(args.message),
                                      load_json(args.review) if args.review else None)
            atomic_save(args.state, updated, args.expected_revision)
            result["revision"] = updated["revision"]
        else:
            updated = record_review(state, **load_json(args.assessment))
            atomic_save(args.state, updated, args.expected_revision)
            result = {"status": "review_recorded", "revision": updated["revision"]}
    print(canon(result))


if __name__ == "__main__":
    main()
