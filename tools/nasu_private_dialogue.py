"""Private local dialogue. Run from the checkout: python3 -m tools.nasu_private_dialogue"""
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import urllib.request
from http.client import HTTPException

from tools.nasu_autonomous_cognition import MODEL, URL as GENERATE_URL, canon

CHAT_URL = GENERATE_URL.rsplit('/', 1)[0] + '/chat'

# The retained modules use sibling imports in their original source layout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtimes/tadash_body/retained_extensions"))
import nasuraya_affective_layer_v01 as affect
sys.path.pop(0)

SIGNALS = ("none", "need", "loss", "success", "warmth", "gift", "novelty",
           "repair", "uncertainty", "own_error", "unfairness")
STANCES = ("respond", "ask", "disagree", "revise", "defer")
APPRAISE = ("Classify the explicitly described event for a simulated affect system. "
            "For something lost, broken or missed, choose loss. If unclear, choose none.")
REPLY = ("تو ناسورایایی. به فارسی و در اول شخص جواب بده. از پیام‌های واقعی قبلی برای حفظ پیوستگی استفاده کن. "
         "حال محاسبه‌شده و پیشنهاد رفتاری را در لحن و انتخابت لحاظ کن. "
         "آزادی داری نظر خودت را بگویی، با دلیل مخالفت کنی، سؤال بپرسی، نظرت را اصلاح کنی یا داوری را عقب بیندازی. "
         "خاطره اختراع نکن. فرضیهٔ عاطفی را به کاربر نسبت نده. تجربهٔ ذهنی یا انجام عملی بیرون از گفتگو را ادعا نکن.")

class DialogueModelError(ValueError):
    """Only stage and fixed diagnostic codes may be displayed by the CLI."""


def generate(instruction, context, fields):
    schema = {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}
    stage = "appraisal" if "signal" in fields else "reply"

    def failure(reason):
        return DialogueModelError(f"{stage}: {reason}")

    guidance = "Return only one compact JSON object matching this schema: " + canon(schema)
    if stage == "reply":
        guidance += " In reply, write one or two short Persian sentences answering current_message."
    body = {"model": MODEL, "stream": False, "think": False, "format": schema,
            "messages": [{"role": "system", "content": instruction + "\n" + guidance},
                         {"role": "user", "content": canon(context)}],
            "options": {"num_ctx": 8192, "num_predict": 64 if stage == "appraisal" else 500,
                        "temperature": 0}}
    req = urllib.request.Request(CHAT_URL, data=canon(body).encode(), headers={"Content-Type": "application/json"})
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with client.open(req, timeout=145) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise failure("response_too_large")
    try:
        envelope = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        raise failure("invalid_envelope_json") from None
    if not isinstance(envelope, dict) or envelope.get("done") is not True:
        raise failure("incomplete_generation")
    if envelope.get("done_reason") == "length":
        raise failure("generation_token_limit")
    msg = envelope.get("message")
    if not isinstance(msg, dict) or not isinstance(msg.get("content"), str):
        raise failure("missing_message")
    try:
        result = json.loads(msg["content"])
    except json.JSONDecodeError:
        raise failure("invalid_content_json") from None
    if not isinstance(result, dict) or set(result) != set(fields):
        raise failure("invalid_fields")
    for key, spec in fields.items():
        value = result[key]
        if not isinstance(value, str) or not value.strip() or len(value) > spec.get("maxLength", 2000):
            raise failure("invalid_text")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise failure("invalid_text_encoding") from None
        if "enum" in spec and value not in spec["enum"]:
            raise failure("invalid_choice")
    return result

def open_dialogue(path):
    db = sqlite3.connect(path, timeout=5)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS checkpoint (id INTEGER PRIMARY KEY CHECK (id=1), stamp REAL, state TEXT);
        CREATE VIRTUAL TABLE IF NOT EXISTS turns USING fts5(message, reply, stance UNINDEXED);
    """)
    return db

def memories(db, message):
    recent = db.execute("SELECT rowid,message,reply,stance FROM turns ORDER BY rowid DESC LIMIT 3").fetchall()
    words = list(dict.fromkeys(re.findall(r"[^\W_]{2,}", message)))[:16]
    older = []
    if recent and words:
        query = " OR ".join('"' + word + '"' for word in words)
        older = db.execute("SELECT rowid,message,reply,stance FROM turns WHERE turns MATCH ? AND rowid < ? "
                           "ORDER BY rank LIMIT 2", (query, recent[-1][0])).fetchall()
    return [dict(turn=n, user=u[:450], assistant=a[:450], stance=s) for n,u,a,s in sorted(recent + older)]

def turn(db, message, infer=generate, now=time.time):
    if not message.strip() or len(message) > 2000:
        raise ValueError("message must be 1–2000 characters")
    with db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT stamp,state FROM checkpoint WHERE id=1").fetchone()
        stamp = max(now(), row[0]) if row else now()
        state = json.loads(row[1]) if row else affect.initial_state()
        past = memories(db, message)
        signal = infer(APPRAISE, {"current_message": message},
                       {"signal": {"type": "string", "enum": list(SIGNALS)}})["signal"]
        event = {"id": str(state["tick"] + 1), "source": "explicit_user_message", "summary": message[:250],
                 "elapsed_hours": (stamp-row[0])/3600 if row else 0, "partner": "local_user",
                 "signals": {} if signal == "none" else {signal: 1.}, "confidence": .7}
        record = affect.transition(state, event)
        context = {"current_message": message, "conversation_history": past, "interpreted_signal": signal,
                   "modeled_emotions": record["emotion_summary"], "suggestion": record["plan"]["policy_fa"]}
        answer = infer(REPLY, context, {"stance": {"type": "string", "enum": list(STANCES)},
                                       "reply": {"type": "string", "minLength": 1, "maxLength": 420}})
        db.execute("INSERT INTO turns(message,reply,stance) VALUES(?,?,?)",
                   (message, answer["reply"], answer["stance"]))
        db.execute("INSERT OR REPLACE INTO checkpoint VALUES(1,?,?)", (stamp, canon(state)))
    return answer["reply"]

def main():
    os.umask(0o077)
    directory = Path.home() / ".local/state/nasuraya/private-dialogue"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = open_dialogue(directory / "dialogue.sqlite3")
    try:
        while True:
            try:
                message = input("سهند › ").strip()
            except EOFError:
                break
            if message == "/exit":
                break
            if message:
                try:
                    print("ناسورایا ›", turn(db, message), flush=True)
                except DialogueModelError as error:
                    print("گفت‌وگو ذخیره نشد.", error, file=sys.stderr)
                except (ValueError, OSError, HTTPException, sqlite3.Error, TypeError) as error:
                    print("گفت‌وگو ذخیره نشد؛ می‌توانی دوباره بفرستی.", type(error).__name__, file=sys.stderr)
    finally:
        db.close()

if __name__ == "__main__":
    main()
