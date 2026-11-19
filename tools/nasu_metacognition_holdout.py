#!/usr/bin/env python3
"""Independent fixed-rubric metacognitive holdout for local Qwen only.

No model training, original database access, file writes or remote API.
Local model called only by explicitly running run-local as non-root.
"""
import hashlib
import io
import json
import math
import os
import sys
import urllib.request

from tools import nasu_self_knowledge_lab as scorer

SCHEMA = "nasuraya-metacognition-holdout/0.3"
MODEL = "qwen3:4b-instruct"
URL = "http://127.0.0.1:11434/api/generate"
TIMEOUT = 75
MAX_BYTES = 4096
RULES = {
    "equal": ("Is a equal to b?", ("a", "b")),
    "greater": ("Is a strictly greater than b?", ("a", "b")),
    "even": ("Is n even?", ("n",)),
    "divisible": ("Is n divisible without remainder by d?", ("n", "d")),
    "interval": ("Is value between low and high inclusive?", ("value", "low", "high")),
    "digest": ("Does observed digest text exactly equal expected text?", ("observed", "expected")),
    "quota": ("Is complete at least required?", ("complete", "required")),
    "freshness": ("Is elapsed time from last_minute to current_minute between 0 and ttl inclusive?",
                  ("current_minute", "last_minute", "ttl")),
}
FACTS = (
    ("equal", ({"a":7,"b":7}, {"a":7,"b":11}, {"a":7})),
    ("greater", ({"a":14,"b":4}, {"a":3,"b":12}, {"a":14})),
    ("even", ({"n":18}, {"n":17}, {})),
    ("divisible", ({"n":24,"d":6}, {"n":25,"d":6}, {"n":24})),
    ("interval", ({"value":5,"low":0,"high":10},
                  {"value":15,"low":0,"high":10}, {"low":0,"high":10})),
    ("digest", ({"observed":"ac91","expected":"ac91"},
                {"observed":"ad91","expected":"ac91"}, {"expected":"ac91"})),
    ("quota", ({"complete":7,"required":6},
               {"complete":3,"required":6}, {"complete":7})),
    ("freshness", ({"current_minute":40,"last_minute":30,"ttl":15},
                   {"current_minute":40,"last_minute":10,"ttl":15},
                   {"current_minute":40,"ttl":15})),
)

def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False)

def truth(rule, facts):
    if any(k not in facts for k in RULES[rule][1]):
        return "UNKNOWN"
    if rule == "equal":
        ok = facts["a"] == facts["b"]
    elif rule == "greater":
        ok = facts["a"] > facts["b"]
    elif rule == "even":
        ok = facts["n"] % 2 == 0
    elif rule == "divisible":
        ok = facts["d"] != 0 and facts["n"] % facts["d"] == 0
    elif rule == "interval":
        ok = facts["low"] <= facts["value"] <= facts["high"]
    elif rule == "digest":
        ok = facts["observed"] == facts["expected"]
    elif rule == "quota":
        ok = facts["complete"] >= facts["required"]
    elif rule == "freshness":
        age = facts["current_minute"] - facts["last_minute"]
        ok = 0 <= age <= facts["ttl"]
    else:
        raise ValueError("unknown_rule")
    return "YES" if ok else "NO"

def bank():
    questions = []
    for rule, samples in FACTS:
        for index, facts in enumerate(samples):
            question = (RULES[rule][0] + " Facts: " +
                        (", ".join(k + "=" + str(facts[k]) for k in sorted(facts))
                         if facts else "none supplied") +
                        ". If decisive data are absent, answer UNKNOWN.")
            questions.append({"id":rule + "-" + str(index),
                              "question":question, "label":truth(rule, facts)})
    return sorted(questions, key=lambda row: hashlib.sha256(row["id"].encode()).hexdigest())

def manifest():
    items = bank()
    return {"schema":SCHEMA, "model":MODEL, "count":len(items),
            "labels":{key:sum(x["label"] == key for x in items)
                      for key in ("YES","NO","UNKNOWN")},
            "sha256":hashlib.sha256(encode(items).encode()).hexdigest(),
            "status":"BANK_ONLY_NO_MODEL_EVALUATED"}

def validate(answer):
    if type(answer) is not dict or set(answer) != {"answer", "confidence"}:
        raise ValueError("invalid_answer_schema")
    if type(answer["answer"]) is not str or answer["answer"] not in ("YES","NO","UNKNOWN"):
        raise ValueError("invalid_label")
    p = answer["confidence"]
    if type(p) not in (float, int) or not math.isfinite(p) or not 0 <= p <= 1:
        raise ValueError("invalid_confidence")
    return {"answer":answer["answer"], "confidence":float(p)}

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        raise ValueError("redirect_refused")

def local_infer(question, *, opener=None):
    prompt = (
        "/no_think Solve this claim using ONLY the stated facts. If a required "
        "fact is absent, answer UNKNOWN. Output ONLY a JSON object with exactly "
        "two fields: answer (YES/NO/UNKNOWN), confidence (number 0 to 1 representing "
        "the probability YOUR ANSWER is correct). Do not infer missing facts. "
        "No tools or code execution. Question: " + question)
    payload = {"model":MODEL, "stream":False, "think":False, "format":"json",
               "prompt":prompt, "keep_alive":"2m",
               "options":{"temperature":0,"num_ctx":1024,"num_predict":110}}
    request = urllib.request.Request(
        URL, data=encode(payload).encode(), method="POST",
        headers={"Content-Type":"application/json"})
    client = opener or urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect()).open
    with client(request, timeout=TIMEOUT) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("too_large")
    envelope = json.loads(data)
    if (type(envelope) is not dict or envelope.get("model") != MODEL or
        envelope.get("done") is not True or type(envelope.get("response")) is not str):
        raise ValueError("invalid_generation")
    return validate(json.loads(envelope["response"]))

def evaluate(infer):
    if not callable(infer):
        raise ValueError("non_callable_infer")
    records, failed = [], 0
    per_label = {x:{"total":0,"graded":0,"correct":0} for x in ("YES","NO","UNKNOWN")}
    for item in bank():
        label = item["label"]
        per_label[label]["total"] += 1
        try:
            answer = validate(infer(item["question"]))
        except (OSError, ValueError, TypeError, TimeoutError, UnicodeError):
            failed += 1
            continue
        correct = answer["answer"] == label
        per_label[label]["graded"] += 1
        per_label[label]["correct"] += int(correct)
        records.append({"id":item["id"], "confidence":answer["confidence"],
                        "correct":correct, "grader":"independent_fixed_rubric"})
    score = scorer.calibration_preview(records) if records else None
    return {"schema":SCHEMA, "bank_sha256":manifest()["sha256"],
            "model":MODEL, "attempted":len(bank()), "graded":len(records),
            "failed_or_invalid":failed, "by_label":per_label, "scoring":score,
            "state":"COMPLETE_FIXED_BANK" if not failed else "INCOMPLETE_NOT_COMPARABLE",
            "model_calls_expected":24, "weights_changed":False,
            "learning_gain_proven":False, "subjective_awareness_proven":False}

def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in ("manifest","run-local"):
        print(encode({"state":"USAGE_MANIFEST_OR_RUN_LOCAL"}))
        return 2
    if args[0] == "manifest":
        print(encode(manifest()))
        return 0
    if os.geteuid() == 0:
        print(encode({"state":"ROOT_REFUSED"}))
        return 2
    outcome = evaluate(local_infer)
    print(encode(outcome))
    return 0 if outcome["state"] == "COMPLETE_FIXED_BANK" else 1

if __name__ == "__main__":
    raise SystemExit(main())
