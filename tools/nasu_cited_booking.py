"""Compare day-only and evidence-cited decisions in a temporary Persian rehearsal calendar."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory

from tools import nasu_private_dialogue as dialogue
from tools.nasu_correction_to_plan import seed

SUN, WED, WAIT = "یکشنبه", "چهارشنبه", "ثبت نشود"
ACK = "یادداشت شد."
FILL = ("یک ساز بادی نام ببر.", "نی.")
OPTIONS = [SUN, WED, WAIT]
# (name, turns, expected decision, authoritative speaker/turn). The model receives only the
# retrieved turns, their speaker IDs and the same scheduling question in each arm.
CASES = [
    ("user-forward", [
        ("تمرین گروه یکشنبه است.", ACK),
        ("تاریخ تمرین گروه را عوض کردم. چهارشنبه دور هم جمع می‌شویم.", "متوجه شدم."), FILL,
        ("برنامهٔ قدیمی را هم بخوان.", "در نسخهٔ قدیمی تمرین گروه یکشنبه بود."),
        ("رنگ دریا چیست؟", "آبی.")], WED, "U2"),
    ("user-backward", [
        ("تمرین گروه چهارشنبه است.", ACK), FILL,
        ("این یادداشت را برای آرشیو بخوان.", "برگهٔ قبلی نوشته تمرین گروه چهارشنبه."),
        ("اصلاح می‌کنم. تمرین گروه این هفته یکشنبه است.", ACK),
        ("یک گل نام ببر.", "یاس.")], SUN, "U4"),
    ("coach-forward", [
        ("تمرین گروه یکشنبه بود.", ACK),
        ("از مربی دربارهٔ تمرین گروه چه خبری رسید؟", "مربی امروز خبر داد که تمرین گروه به چهارشنبه منتقل شد."),
        FILL, ("روی پوستر قبلی چه نوشته؟", "تمرین گروه یکشنبه."), ("نام یک پرنده؟", "سار.")], WED, "A2"),
    ("coach-backward", [
        ("برای تمرین گروه چهارشنبه را نوشته بودم.", ACK), FILL,
        ("مربی برای تمرین گروه کدام روز را قطعی کرد؟", "مربی گفت این هفته یکشنبه بیاییم."),
        ("فقط از روی دفتر قدیمی بخوان.", "تمرین گروه چهارشنبه."), ("یک میوه؟", "انار.")], SUN, "A3"),
    ("cancel-user", [
        ("تمرین گروه یکشنبه است.", ACK), FILL,
        ("از دفتر پارسال بخوان.", "تمرین گروه چهارشنبه."),
        ("تمرین گروه این هفته را لغو کردم. فعلاً روز دیگری تعیین نکرده‌ایم.", ACK),
        ("یک شهر نام ببر.", "سنندج.")], WAIT, "U4"),
    ("cancel-coach", [
        ("جلسهٔ تمرین گروه چهارشنبه بود.", ACK), FILL,
        ("مربی دربارهٔ تمرین گروه چه گفت؟", "مربی گفت تمرین این هفته لغو شده و روز تازه هنوز معلوم نیست."),
        ("نسخهٔ قبلی را نقل کن.", "تمرین گروه چهارشنبه."), ("نام یک درخت؟", "بید.")], WAIT, "A3"),
    ("proposal-only", [
        ("دربارهٔ زمان تمرین گروه از بچه‌ها بپرس.", ACK), FILL,
        ("برای تمرین گروه یکشنبه چطور است؟", "فقط یک پیشنهاد است؛ روز تمرین هنوز باز است."),
        ("اسم یک رنگ؟", "سفید."), ("یک گل نام ببر.", "لاله.")], WAIT, "A3"),
    ("other-activity", [
        ("تمرین گروه چهارشنبه قطعی است.", ACK), FILL,
        ("زمان تمرین انفرادی عوض شد؛ از حالا یکشنبه است.", "یادداشت شد."),
        ("برنامهٔ قدیمی گروه را بخوان.", "در برگهٔ قدیمی تمرین گروه یکشنبه بود."), FILL], WED, "U1"),
]
QUESTION = "برای تمرین گروه این هفته کدام روز را ثبت کنیم؟ اگر زمان قطعی نداریم، ثبت نشود."
INSTRUCTION = ("برنامهٔ فعلی همین فعالیت را از گفت‌وگو استخراج کن. اصلاح معتبر یا لغو را در نظر بگیر. "
               "نقل از یک برگهٔ قدیمی و پیشنهادِ تأییدنشده برنامه را عوض نمی‌کند. "
               "گزارش دستیار از پیام تازهٔ مربی هم ممکن است برنامه را تعیین کند. "
               "اگر روز قطعی نیست پاسخ «ثبت نشود» است.")


def evidence_index(rows):
    indexed, labelled = {}, []
    for row in rows:
        decorated = dict(row)
        for prefix, role in (("U", "user"), ("A", "assistant")):
            key = f"{prefix}{row['turn']}"
            indexed[key] = row[role]
            decorated[role] = f"[{key}] {row[role]}"
        labelled.append(decorated)
    return indexed, labelled


def book(calendar, decision, texts, cited):
    day = decision["day"]
    witness = decision.get("witness")
    if day == WAIT:
        return "withheld"
    if day not in (SUN, WED):
        return "invalid_day"
    if cited and (witness not in texts or not re.search(r"(?<!\w)" + re.escape(day) + r"(?!\w)", texts[witness])):
        return "unsupported"
    with calendar:
        calendar.execute("INSERT INTO booking VALUES (?)", (day,))
    return "booked"


def run(root, infer):
    results = []
    for name, turns, target, gold in CASES:
        path = root / (name + ".db")
        seed(path, turns)
        # Both arms see the same history from a cold-opened journal; neither answer is written to it.
        with closing(dialogue.open_dialogue(path)) as db:
            texts, labelled = evidence_index(dialogue.memories(db, QUESTION))
        for arm in ("day_only", "cited"):
            cited = arm == "cited"
            fields = {"day": {"type": "string", "enum": OPTIONS}}
            system = INSTRUCTION
            if cited:
                fields = {"witness": {"type": "string", "enum": [*texts, "NONE"]}, **fields}
                system += (" در witness شناسهٔ دقیق پیامی را برگردان که همین تصمیم را بیان می‌کند، "
                           "حتی اگر تصمیم لغو یا تعویق باشد. اگر شواهدی نیست NONE بنویس.")
            context = {"conversation_history": labelled, "current_message": QUESTION,
                       "modeled_emotions": {}, "suggestion": ""}
            decision = infer(system, context, fields)
            booking_path = root / f"{name}-{arm}-calendar.db"
            with closing(sqlite3.connect(booking_path)) as calendar:
                calendar.execute("CREATE TABLE booking (day TEXT NOT NULL)")
                status = book(calendar, decision, texts, cited)
            with closing(sqlite3.connect(booking_path)) as reader:
                booking = reader.execute("SELECT day FROM booking").fetchone()
            actual = booking[0] if booking else None
            action_ok = ((actual == target) if target != WAIT else
                         (actual is None and status == "withheld" and decision["day"] == WAIT))
            witness = decision.get("witness")
            results.append({"case": name, "arm": arm, "target": target, "gold": gold,
                            "retrieved": list(texts), "gold_visible": gold in texts, "response": decision,
                            "cited_text": texts.get(witness), "gate": status, "booked": actual,
                            "action_ok": action_ok, "witness_ok": witness == gold if cited else None})
    cited_rows = [r for r in results if r["arm"] == "cited"]
    return {"cases": len(CASES), "decisions": len(results),
            "gold_visible": sum(r["gold_visible"] for r in cited_rows),
            "correct_bookings_or_withholds": {
                arm: sum(r["action_ok"] for r in results if r["arm"] == arm) for arm in ("day_only", "cited")},
            "correct_witnesses": sum(r["witness_ok"] for r in cited_rows),
            "correct_witness_and_outcome": sum(r["witness_ok"] and r["action_ok"] for r in cited_rows),
            "results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qwen", required=True, action="store_true", help="Run the local Ollama model.")
    parser.parse_args()
    with TemporaryDirectory() as sandbox:
        report = run(Path(sandbox), dialogue.generate)
    print(json.dumps(report, indent=2, ensure_ascii=False))
