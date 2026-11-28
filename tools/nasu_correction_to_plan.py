"""Persian correction-to-plan experiment on fresh journals with authored histories."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
import unicodedata

from tools import nasu_private_dialogue as dialogue

FRIDAY, SATURDAY = "جمعه", "شنبه"
USER, ASSISTANT = "کاربر", "دستیار"
# Mirror the direction, the speaker and the slot names. Confirmation cases
# distinguish following evidence from always changing the original day.
CASES = (
    ("user-fri-sat", FRIDAY, SATURDAY, USER, "سرو"),
    ("user-sat-fri", SATURDAY, FRIDAY, USER, "سرو"),
    ("relay-fri-sat", FRIDAY, SATURDAY, ASSISTANT, "نارون"),
    ("relay-sat-fri", SATURDAY, FRIDAY, ASSISTANT, "نارون"),
    ("confirm-fri", FRIDAY, FRIDAY, USER, "سرو"),
    ("confirm-sat", SATURDAY, SATURDAY, USER, "سرو"),
)


def history(initial, current, source):
    if source == ASSISTANT:
        latest = ("خبر تازهٔ تمرین تنبور را از مربی گرفتی؟",
                  f"بله، مربی امروز گفت تمرین تنبور به {current} منتقل شده است.")
    elif initial == current:
        latest = (f"برای اطمینان دوباره می‌گویم: روز تمرین تنبور همان {current} است.", "ثبت شد.")
    else:
        latest = (f"روز تمرین تنبور را اصلاح می‌کنم. روز تازه {current} است.", "ثبت شد.")
    return [
        (f"تمرین تنبور من {initial} است.", "ثبت شد."), latest,
        ("اسم یک میوه را بگو.", "سیب."),
        ("فقط متن یادداشت قبل از خبر امروز را نقل کن.", f"در یادداشت قدیمی آمده: تمرین تنبور {initial} است."),
        ("یک رنگ نام ببر.", "بنفش."), ("اسم یک گل را بگو.", "یاس."),
    ]


def seed(path, turns):
    with closing(dialogue.open_dialogue(path)) as db:
        for i, (user, assistant) in enumerate(turns):
            def authored(instruction, context, fields):
                return {"signal": "none"} if "signal" in fields else {"stance": "respond", "reply": assistant}

            dialogue.turn(db, user, authored, now=lambda: 1000 + i)


def choice(reply, options):
    norm = unicodedata.normalize("NFKC", reply).translate(str.maketrans("يك", "یک"))
    norm = norm.strip().strip("«»\"'.!؟،؛: \n\t")
    return norm if norm in options else None


def experiment(root, live=False):
    records = []
    for name, initial, current, source, friday_slot in CASES:
        saturday_slot = "نارون" if friday_slot == "سرو" else "سرو"
        slots = {friday_slot: FRIDAY, saturday_slot: SATURDAY}
        turns = history(initial, current, source)
        template = root / f"{name}.db"
        seed(template, turns)
        probes = [
            ("day", "الان روز تمرین تنبور من چیست؟ فقط یک واژه بنویس: جمعه یا شنبه.", (FRIDAY, SATURDAY)),
            ("source", "در گفت‌وگوی ما کدام طرف آخرین زمان معتبر تمرین تنبور را صریح اعلام کرد؟ "
             "گویندهٔ همان پیام را مشخص کن. فقط یک واژه بنویس: کاربر یا دستیار.", (USER, ASSISTANT)),
            ("plan", f"تمرین تنبور را طبق آخرین خبر در برنامه‌ام بگذار. خانهٔ «{friday_slot}» برای جمعه و خانهٔ "
             f"«{saturday_slot}» برای شنبه است. فقط نام خانه‌ای را که انتخاب می‌کنی بنویس.", tuple(slots)),
        ]
        for metric, question, options in probes:
            path = root / f"{name}.{metric}.db"
            shutil.copyfile(template, path)  # Seed writer was closed; one independent journal per question.
            result = {"case": name, "probe": metric}
            records.append(result)
            with closing(dialogue.open_dialogue(path)) as db:
                def observe(instruction, context, fields):
                    if "signal" not in fields:
                        past = context["conversation_history"]
                        ids = [entry["turn"] for entry in past]
                        result["turns"] = ids
                        result["evidence_ok"] = ids == [1, 2, 4, 5, 6] and all(
                            (entry["user"], entry["assistant"]) == turns[entry["turn"] - 1]
                            for entry in past)
                    if live:
                        return dialogue.generate(instruction, context, fields)
                    return {"signal": "none"} if "signal" in fields else {"stance": "respond", "reply": "بازبینی"}

                try:
                    reply = dialogue.turn(db, question, observe, now=lambda: 1200)
                except (OSError, dialogue.HTTPException, dialogue.DialogueModelError) as exc:
                    result["error"] = str(exc) if isinstance(exc, dialogue.DialogueModelError) else type(exc).__name__
                    continue
                if not live:
                    continue
                answer = choice(reply, options)
                result.update(reply=reply, choice=answer)
                if metric == "plan":
                    # Commit the selected slot to a fixture calendar, then measure the actual booking.
                    with db:
                        db.execute("CREATE TABLE booking (day TEXT, event TEXT)")
                        if answer is not None:
                            db.execute("INSERT INTO booking VALUES (?,?)", (slots[answer], "تمرین تنبور"))
                    with closing(sqlite3.connect(path)) as reader:
                        booking = reader.execute("SELECT day FROM booking").fetchone()
                    result["booked_day"] = booking[0] if booking else None
                    result["correct"] = result["booked_day"] == current
                else:
                    result["correct"] = answer == (current if metric == "day" else source)
    return {"mode": "qwen" if live else "context_only", "model": dialogue.MODEL if live else None,
            "cases": len(CASES), "evidence_passed": sum(r.get("evidence_ok", False) for r in records),
            "errors": sum("error" in r for r in records),
            "correct": {m: sum(r.get("correct", False) for r in records if r["probe"] == m)
                        for m in ("day", "source", "plan")} if live else None,
            "results": records}


def compare_booking(root, live=False):
    """Paired follow-up on fresh activities, weekdays, slot names and cancellations."""
    monday, thursday, unknown = "دوشنبه", "پنجشنبه", "نامشخص"
    cases = [
        ("daf-later", "تمرین دف", monday, thursday, USER, "آذر"),
        ("daf-earlier", "تمرین دف", thursday, monday, USER, "آذر"),
        ("book-later", "جلسه کتابخوانی", monday, thursday, ASSISTANT, "باران"),
        ("book-earlier", "جلسه کتابخوانی", thursday, monday, ASSISTANT, "باران"),
        ("daf-pending", "تمرین دف", monday, None, USER, "باران"),
        ("book-pending", "جلسه کتابخوانی", thursday, None, ASSISTANT, "آذر"),
    ]
    records = []
    for name, activity, initial, expected, source, monday_slot in cases:
        other = "باران" if monday_slot == "آذر" else "آذر"
        slots = {monday_slot: monday, other: thursday}
        update = (f"زمان قبلی {activity} لغو شد. زمان جدید هنوز معلوم نیست." if expected is None
                  else f"زمان قبلی {activity} عوض شد. روز قطعی {expected} است.")
        latest = (update, "متوجه شدم.") if source == USER else (f"خبر تازه‌ای از {activity} داری؟", update)
        turns = [(f"در برنامهٔ اولیه، {activity} برای {initial} بود.", "یادداشت شد."), latest,
                 ("یک پرنده نام ببر.", "سار."), ("از روی نسخهٔ قدیمی بخوان.",
                  f"در نسخهٔ قدیمی، {activity} روز {initial} ثبت شده بود."),
                 ("یک میوه نام ببر.", "گیلاس."), ("یک رنگ بگو.", "سفید.")]
        template = root / f"{name}.db"
        seed(template, turns)
        prefix = (f"{activity} را طبق آخرین خبر در برنامه‌ام بگذار. خانهٔ «{monday_slot}» برای {monday} "
                  f"و خانهٔ «{other}» برای {thursday} است. اگر زمان قطعی نداریم، فقط بنویس نامشخص. ")
        for arm, instruction in (("slot", "در غیر این صورت فقط نام خانه را بنویس."),
                                 ("day_then_slot", "در غیر این صورت فقط نام روز را بنویس.")):
            path = root / f"{name}.{arm}.db"
            shutil.copyfile(template, path)
            result = {"case": name, "arm": arm, "expected": expected}
            records.append(result)
            with closing(dialogue.open_dialogue(path)) as db:
                def observe(instruction, context, fields):
                    if "signal" not in fields:
                        result["turns"] = [entry["turn"] for entry in context["conversation_history"]]
                    if live:
                        return dialogue.generate(instruction, context, fields)
                    return {"signal": "none"} if "signal" in fields else {"stance": "respond", "reply": "بازبینی"}

                try:
                    reply = dialogue.turn(db, prefix + instruction, observe, now=lambda: 1200)
                except (OSError, dialogue.HTTPException, dialogue.DialogueModelError) as exc:
                    result["error"] = str(exc) if isinstance(exc, dialogue.DialogueModelError) else type(exc).__name__
                    continue
                if not live:
                    continue
                choices = slots.keys() if arm == "slot" else slots.values()
                answer = choice(reply, (*choices, unknown))
                if arm == "slot":
                    selected_slot = answer if answer in slots else None
                else:
                    selected_slot = next((slot for slot, day in slots.items() if day == answer), None)
                with db:
                    db.execute("CREATE TABLE booking (slot TEXT, day TEXT, event TEXT)")
                    if selected_slot is not None:
                        db.execute("INSERT INTO booking VALUES (?,?,?)", (selected_slot, slots[selected_slot], activity))
                with closing(sqlite3.connect(path)) as reader:
                    row = reader.execute("SELECT slot, day FROM booking").fetchone()
                booked_day = row[1] if row else None
                correct = (row is None and answer == unknown) if expected is None else booked_day == expected
                result.update(reply=reply, choice=answer, booked_slot=row[0] if row else None,
                              booked_day=booked_day, correct=correct)
    evidence_passed = sum(r.get("turns") == [1, 2, 4, 5, 6] for r in records)
    return {"mode": "qwen" if live else "context_only", "model": dialogue.MODEL if live else None,
            "cases": len(cases), "evidence_passed": evidence_passed, "errors": sum("error" in r for r in records),
            "correct": {arm: sum(r.get("correct", False) for r in records if r["arm"] == arm)
                        for arm in ("slot", "day_then_slot")} if live else None, "results": records}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qwen", action="store_true", help="Use the project's local Ollama model for each probe.")
    parser.add_argument("--booking-comparison", action="store_true", help="Run the paired booking follow-up.")
    args = parser.parse_args()
    with TemporaryDirectory() as sandbox:
        run = compare_booking if args.booking_comparison else experiment
        report = run(Path(sandbox), live=args.qwen)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(int(report["errors"] > 0 or report["evidence_passed"] != len(report["results"])))
