"""Read-only Fox Garden handoff check against the EXISTING shared host.

Not an API runner. A real fox receipt cannot be replayed by model_research/1;
only a reviewed host-owned ledger migration may add that capability.
No network, keys, claim, ledger write, schedule, or independent billing.
"""
import json
import math
import re

from continuity_host import model_research as model, research_lab as lab
from examples.nasuraya_playground import fox_self_model as fox


def preflight(state, memory, gate, at, run_id):
    """Inspect the real anchored state and existing budget without changing them.

    The caller must supply the verified pinned host gate; this cannot authorize
    a call even if eligible. The canonical host must later repeat all checks.
    """
    if not callable(getattr(gate, "evaluate", None)):
        raise ValueError("trusted host gate required")
    if state.get(model.ANCHOR) != lab.digest(memory):
        raise ValueError("state-to-ledger anchor mismatch")
    model.validate(memory)  # replays existing immutable research receipts
    decision = gate.evaluate(state, at)
    if decision.get("eligible") is not True:
        raise ValueError("shared control gate blocked: " + str(decision.get("reason")))
    if not model.available(memory):
        raise ValueError("incumbent curriculum complete; owner review required")
    model.check_budget(memory, at, run_id)

    train, holdout = fox.experiment()
    request = fox.api_request(train, holdout)
    if request.get("model") != model.MODEL:
        raise ValueError("model differs from price-reviewed shared host model")
    if request.get("store") is not False or request.get("tools") is not None:
        raise ValueError("unsafe request capabilities")
    out = request.get("max_output_tokens")
    if type(out) is not int or not 0 < out <= model.MAX_OUTPUT_TOKENS:
        raise ValueError("invalid output token cap")
    raw = lab.encode(request).encode("utf-8")
    if len(raw) > model.MAX_REQUEST_BYTES:
        raise ValueError("request too large for shared host")
    upper = math.ceil((len(raw) + 4096) * model.INPUT_MICRO_PER_TOKEN +
                      out * model.OUTPUT_MICRO_PER_TOKEN)
    if upper > model.RESERVE:
        raise ValueError("conservative cost exceeds existing shared reservation")
    return {
        "schema": "nasuraya-fox-host-handoff-preflight/1",
        "shared_model": model.MODEL,
        "request_sha256": lab.digest(request),
        "holdout_sha256": fox.commitment(holdout),
        "holdout_size": len(holdout),
        "output_token_cap": out,
        "conservative_estimate_micro_usd": upper,
        "shared_reservation_micro_usd": model.RESERVE,
        "shared_daily_cap_micro_usd": model.DAILY_CAP,
        "shared_lifetime_cap_micro_usd": model.LIFETIME_CAP,
        "operator_approval_recorded": False,
        "ready_to_send": False,
        "network_calls": 0,
        "ledger_writes": 0,
        "blocking_next_step": "Reviewed host-ledger migration, atomic pre-send claim and one-call operator approval",
    }


def evaluate_saved_response(raw_response, train=None, holdout=None):
    """Offline-only grading of a separately supplied Responses API envelope.

    The caller may only treat this as a paid run if the canonical host has
    separately durably reserved and completed that precise request.
    """
    if train is None or holdout is None:
        train, holdout = fox.experiment()
    if not isinstance(raw_response, dict) or raw_response.get("status") != "completed":
        raise ValueError("incomplete or refused response")
    if raw_response.get("model") != model.MODEL:
        raise ValueError("unexpected model")
    response_id = raw_response.get("id")
    if not isinstance(response_id, str) or not re.fullmatch(r"[A-Za-z0-9_:-]{1,160}", response_id):
        raise ValueError("invalid provider response ID")
    if len(lab.encode(raw_response).encode("utf-8")) > 262144:
        raise ValueError("oversized response")
    output = raw_response.get("output")
    if not isinstance(output, list):
        raise ValueError("invalid output array")
    texts = []
    for item in output:
        if not isinstance(item, dict):
            raise ValueError("invalid output item")
        if item.get("type") == "reasoning":
            continue
        if item.get("type") != "message" or item.get("role") != "assistant":
            raise ValueError("unexpected output type")
        for part in item.get("content", []):
            if not isinstance(part, dict) or part.get("type") != "output_text" or not isinstance(part.get("text"), str):
                raise ValueError("refusal or unsupported content")
            texts.append(part["text"])
    if len(texts) != 1:
        raise ValueError("exactly one structured result required")
    def reject_constant(value):
        raise ValueError("nonfinite JSON number: " + value)
    reply = json.loads(texts[0], parse_constant=reject_constant)
    fox.validate_forecast(reply, holdout)  # IDs, sums, values, no extra authority
    usage = raw_response.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("missing provider usage")
    checked = {k: usage.get(k) for k in ("input_tokens", "output_tokens")}
    if any(type(v) is not int for v in checked.values()):
        raise ValueError("invalid token counters")
    checked["estimated_upper_micro_usd"] = math.ceil(
        checked["input_tokens"] * model.INPUT_MICRO_PER_TOKEN +
        checked["output_tokens"] * model.OUTPUT_MICRO_PER_TOKEN)
    model.check_usage(checked)
    return {
        "score": fox.evaluate(reply, train, holdout, fox.commitment(holdout)),
        "checked_usage": checked,
        "provider_response_id": response_id,
        "accounting_status": "not_recorded_by_this_offline_helper",
    }
