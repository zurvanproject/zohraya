"""Offline projection of pinned public reports; neither identity nor action authority.

The reused witness supplies lexical validation, not an authenticity decision.
This adapter deliberately does not call its obsolete request registry or fetcher.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


SCHEMA = "dios.unified-evidence.v1"
FRESHNESS_SECONDS = 300
_ROOT = Path(__file__).resolve().parent / "evidence_sources"
_PINS = {
    "fourway_evidence_gate_v02.py": "7ab8945804dc5bd868d14336c358ce56c788ebd3d2cedf8ca914825863845843",
    "public_ci_witness.py": "74fdc0be95604acdb7000f45ff7c55ce6b11dcc00d71b1020b1e31342e946cab",
    "receipt.json": "5d14d1d6d71091555d06b2a18619101580533f7e665f061df2eacb0c27c68ea8",
    "receipts.json": "4416bd74bb23fc115aba1865703d1e9f3e3eda31f06ac64d71f6b7f791e1ac12",
    "ritual_mastery_status_v01.json": "df3a2325674804128adde41226b94b363be905d4dcf4d59a77e5deb46d6d4c7b",
    "visual_director.py": "bf5d6ffec138a0256e0818c0844abe1f8b9db54ee79d843122822040addc61d4",
    "provenance.json": "119dac9c1632110143877b483f2f4e6b0b96a1dea48b1d9367bcabd343850980",
}
_UTC = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)\Z", re.ASCII)
_NAMES = frozenset(("research", "atlas", "desktop"))


def _assets() -> dict:
    result = {}
    for filename, expected in _PINS.items():
        raw = (_ROOT / filename).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("evidence_source_pin_mismatch:" + filename)
        if filename.endswith(".json"):
            result[filename] = json.loads(raw)
    return result


_assets()  # Check exact bytes before importing the unchanged witness dependency.
from .evidence_sources import fourway_evidence_gate_v02 as _witness


def _utc(value: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise ValueError("aware_utc_timestamp_required")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid_utc_timestamp") from exc


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_receipt_shape") from exc


def _source(assets: dict, filename: str) -> dict:
    return next(item.copy() for item in assets["provenance.json"]["sources"]
                if item["local_path"] == filename)


def validate_receipt(name: str, record: dict, *, now_utc: str) -> dict:
    """Validate only one exact frozen manifest record, without authenticating it.

    No caller-provided observation, owner flag, or new request can enter this bus.
    Accepting a byte-equivalent record means consistency with the fixed fixture.
    """
    if not isinstance(name, str) or name not in _NAMES or type(record) is not dict:
        raise ValueError("unknown_receipt")
    now = _utc(now_utc)
    assets = _assets()
    expected = assets["receipts.json"][name]
    if set(record) != set(expected):
        raise ValueError("unexpected_receipt_fields")
    for key, value in record.items():
        if type(value) is not type(expected[key]):
            raise ValueError("invalid_receipt_field_type")
        if isinstance(value, str) and len(value) > 1000:
            raise ValueError("oversized_receipt_field")
    fields = _witness.parse_summary_fields(record["summary"])
    if fields is None:
        raise ValueError("invalid_summary_fields")
    request = f"nasu: run {record['job_commit']} {record['job']} {record['job_sha256']}"
    reply = (f"Nasuraya Bridge v2 result; request_id=comment-{record['request_id']}; "
             f"command=run {record['job']}\nResult: {record['summary']}")
    match = _witness.REPLY_RE.fullmatch(reply)
    if match is None or int(match.group(1)) != record["request_id"]:
        raise ValueError("invalid_reply_binding")
    for prefix, body in (("request_body", request), ("receipt_body", reply),
                         ("summary", record["summary"])):
        if _sha(body) != record[prefix + "_sha256"]:
            raise ValueError("receipt_digest_mismatch")
    for id_key, owner_key, body in (("request_id", "owner_login", request),
                                    ("reply_id", "reply_owner_login", reply)):
        if not _witness.owner_comment({"id": record[id_key],
                                     "user": {"login": record[owner_key]}, "body": body}):
            raise ValueError("receipt_owner_field_mismatch")
    if _canonical(record) != _canonical(expected):
        raise ValueError("pinned_receipt_manifest_mismatch")
    created = _utc(record["receipt_utc"])
    requested = _utc(record["request_utc"])
    if created > now or requested > now:
        raise ValueError("future_receipt")
    if created < requested or record["reply_id"] <= record["request_id"]:
        raise ValueError("invalid_receipt_order")
    age = (now - created).total_seconds()
    provenance = {key: record[key] for key in (
        "repository", "issue_number", "request_id", "request_utc", "reply_id",
        "receipt_utc", "job", "job_commit", "job_sha256", "request_body_sha256",
        "receipt_body_sha256", "summary_sha256")}
    provenance["request_url"] = _witness.public_comment_url(record["request_id"])
    provenance["receipt_url"] = _witness.public_comment_url(record["reply_id"])
    result = {
        "name": name,
        "provenance": provenance,
        "evidence_tier": "OWNER_ACCOUNT_REPORT",
        "validation": "CONSISTENT_WITH_PINNED_PUBLIC_FIXTURE",
        "source_authenticated": False,
        "live_execution_verified": False,
        "action_authority": False,
        "freshness": "FRESH_REPORT" if age <= FRESHNESS_SECONDS else "HISTORICAL_REPORT",
        "report_age_seconds": age,
        "freshness_policy_seconds": FRESHNESS_SECONDS,
        "reported_fields": fields,
    }
    if name == "research":
        result["derived"] = {
            "state": "COMPLETED_REPORTED",
            "active_worker_verified": False,
            "reported_heartbeat_stale": int(fields["STALE_MIN"]) * 60 > FRESHNESS_SECONDS,
            "counts": {key.lower(): int(fields[key]) for key in
                       ("CYCLES", "ROLYEL", "BAD", "TESTS", "TF", "BODYTOY", "AUDIT")},
            "count_units": "job_reported_counters_not_independently_recounted",
        }
    elif name == "atlas":
        result["derived"] = {
            "state": "INVENTORY_REPORTED",
            "counts": {key.lower(): int(fields[key]) for key in
                       ("NODES", "SYSTEMS", "ROUTES", "EXTRA")},
            "physical_simulation_verified": False,
        }
    else:
        desktop = assets["receipt.json"]
        if (desktop["request_comment_id"] != record["request_id"] or
                desktop["receipt_comment_id"] != record["reply_id"] or
                desktop["observed_receipt"] != record["summary"]):
            raise ValueError("desktop_receipt_document_mismatch")
        provenance["document"] = _source(assets, "receipt.json")
        result["derived"] = {
            "state": "WEB_SHORTCUTS_CREATED_REPORTED",
            "shortcut_count_reported": len(desktop["shortcuts"]),
            "requires_interactive_login": desktop["requires_interactive_login"],
            "browser_compatibility_verified": desktop["browser_compatibility_verified"],
            "authenticated_chat_or_image_generation_tested": desktop[
                "authenticated_chat_or_image_generation_tested"],
            "native_ai_apps_installed_verified": False,
            "local_models_installed_verified": False,
            "paid_api_calls_reported": desktop["paid_api_calls"],
            "paid_api_calls_by_adapter": 0,
        }
    return result


def snapshot(*, now_utc: str) -> dict:
    """Return frozen observations at an explicit UTC evaluation time; no I/O outside files."""
    now = _utc(now_utc)
    assets = _assets()
    ritual = assets["ritual_mastery_status_v01.json"]
    ritual_states = {name: {key: state[key] for key in (
        "stage", "mastered", "delayed_cold_recall_passes", "unassisted_cold_recall_passes")}
        for name, state in ritual["states"].items()}
    return {
        "schema": SCHEMA,
        "evaluated_at_utc": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "clock_source": "caller_supplied_evaluation_time_not_attestation",
        "freshness_policy_seconds": FRESHNESS_SECONDS,
        "receipts": {name: validate_receipt(name, record, now_utc=now_utc)
                     for name, record in assets["receipts.json"].items()},
        "ritual": {
            "provenance": _source(assets, "ritual_mastery_status_v01.json"),
            "evidence_tier": "PINNED_AUTHORED_PROJECT_STATE",
            "freshness": "NOT_A_LIVE_OBSERVATION",
            "authored_date": ritual["updated"], "states": ritual_states,
            "independent_mastery_verified": False,
            "body_learning_proven": ritual["limits"]["body_learning_proven"],
            "model_weights_changed": ritual["limits"]["model_weights_changed"],
            "minimum_complete_passes_per_session": ritual["training_protocol"][
                "minimum_complete_passes_per_session"],
            "same_session_passes_are_distinct_sessions": False,
            "physiological_arousal_claim": False,
            "action_authority": False,
        },
        "visual": {
            "provenance": _source(assets, "visual_director.py"),
            "evidence_tier": "PINNED_SOURCE_CAPABILITY_DESCRIPTION",
            "freshness": "NOT_A_LIVE_OBSERVATION",
            "state": "PLAN_ONLY", "rendered": False, "generator_calls": 0,
            "provider_approved": None, "actual_visual_rendering_wired": False,
            "adapter_executes_visual_director": False,
            "human_review_authenticated": False,
            "action_authority": False,
        },
        "witness_provenance": _source(assets, "fourway_evidence_gate_v02.py"),
        "source_authentication_verified": False,
        "live_execution_verified": False,
        "action_authority": False,
        "execution_permitted": False,
        "external_actions_taken": 0,
        "network_calls": 0,
    }
