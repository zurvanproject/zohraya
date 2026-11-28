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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qwen", action="store_true", help="Use the project's local Ollama model for each probe.")
    args = parser.parse_args()
    with TemporaryDirectory() as sandbox:
        report = experiment(Path(sandbox), live=args.qwen)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(int(report["errors"] > 0 or report["evidence_passed"] != len(report["results"])))
