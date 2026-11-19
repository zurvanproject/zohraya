#!/usr/bin/env python3
"""ATMOSPHERE: public-domain verse + synchronous, symbolic ritual cues.

Produces an offline *plan*, not an executed ritual, audio, motion, or approval.
Quoted literature and external commentary remain non-authoritative data.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re

try:
    from .atmosphere_policy import authorize, classify_external_text
except ImportError:
    from atmosphere_policy import authorize, classify_external_text

SCHEMA = "atmosphere-poetic-ritual/1"
SOURCE = Path(__file__).resolve().parents[1] / "docs/rituals/sources/shahnameh_haft_khan_ganjoor_full.md"
PHASES = (
    ("jing", "بدن / زمین", "بیت را همراه حرکت نرم و توجه به تکیه‌گاهِ واقعی بخوان."),
    ("qi", "شاهد / توجه", "بیت را دوباره همراه همان حرکت بخوان؛ حس واقعی را از خیال تفکیک کن."),
    ("shen", "اختیار / بازبینی", "بیت را بار سوم بخوان، حرکت را پایان بده و یک تصمیم محدود ثبت کن."),
)
# Exact adjacent verse lines, checked against their corresponding Shahnameh section.
# All movement/cognition/interpretation here is contemporary, not attributed to Ferdowsi.
STAGES = (
    (1, 5, "رخش و شیر", ("تن رخش بسترد و زین برنهاد", "ز یزدان نیکی دهش کرد یاد"),
     "کف دو دست را آرام روی ران‌ها بگذار و رها کن.",
     "تماس واقعی دست را از تصویر ذهنی رخش جدا کن.",
     "آیا پیش از واکنش به هشدار همراه خود گوش می‌دهم؟"),
    (2, 6, "بیابان و چشمه", ("به ره بر یکی چشمه آمد پدید", "چو میش سراور بدانجا رسید"),
     "یک کف دست را نرم رو به بالا باز کن و پایین بیاور.",
     "یک نیاز واقعی مثل استراحت را نام ببر؛ محرومیت یا تشنگی ایجاد نکن.",
     "آیا نیاز به آب، استراحت یا کمک را به‌موقع می‌پذیرم؟"),
    (3, 7, "اژدها", ("چنان ساخت روشن جهان‌آفرین", "که پنهان نکرد اژدها را زمین"),
     "دست را باز کن و چشم‌ها را به اتاق روشن برگردان.",
     "یک واقعیت مشاهده‌شده، یک خیال و یک مجهول را جدا نام ببر.",
     "آیا هنگام کمبود شواهد می‌توانم بگویم «نمی‌دانم»؟"),
    (4, 8, "زن جادو", ("چو آواز داد از خداوند مهر", "دگرگونه‌تر گشت جادو به چهر"),
     "دو کف باز را رو‌به‌روی هم بگیر و سپس کنار بدن رها کن.",
     "جذابیت یا ترس روایت را دلیل مستقل درباره انسان واقعی ندان.",
     "برای داوری در مورد دیگری چه شاهد قابل بررسی دارم؟"),
    (5, 9, "تاریکی و اولاد", ("وزانجا سوی روشنایی رسید", "زمین پرنیان دید و یکسر خوید"),
     "شانه‌ها را آرام رها کن و یک نقطه واقعی را نگاه کن.",
     "واکنش خشن به دشتبان در داستان را الگوی اخلاقی ندان.",
     "وقتی اختیار دارم، چگونه از آسیب بی‌دلیل جلوگیری می‌کنم؟"),
    (6, 10, "ارژنگ دیو", ("یکی نعره زد در میان گروه", "تو گفتی بدرید دریا و کوه"),
     "دست نیمه‌بسته را آرام باز کن؛ فریاد یا ضربه نزن.",
     "هیجان تصویر حماسی را با فرمان خشونت در زندگی واقعی اشتباه نگیر.",
     "آیا قدرت تصمیم را بدون پرخاش نگه می‌دارم؟"),
    (7, 11, "دیو سپید و پیمان", ("به پیمان شکستن نه اندر خوری", "که شیر ژیانی و کی منظری"),
     "کف دست را بی‌فشار روی سینه یا ران بگذار و رها کن.",
     "بهبود دید در داستان استعاره روایی است، نه مداخله پزشکی.",
     "کدام پیمان محدود و قابل‌سنجش را در عمل پاس می‌دارم؟"),
)

def load_verses(path=SOURCE):
    """Read a bounded exact source and validate all seven section-specific excerpts."""
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000:
        raise ValueError("source absent, symlinked or oversized")
    raw = path.read_bytes()
    book = raw.decode("utf-8")
    headings = list(re.finditer(r"(?m)^بخش ([۰-۹]+) - خان [^\n]+$", book))
    numbers = [int(h.group(1).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))) for h in headings]
    if numbers != list(range(5, 12)):
        raise ValueError("unexpected source chapter sequence")
    chapters = {}
    for i, h in enumerate(headings):
        finish = headings[i + 1].start() if i + 1 < len(headings) else len(book)
        chapters[numbers[i]] = book[h.end():finish].strip()
    for khan, section, _, verse, *_ in STAGES:
        if "\n".join(verse) not in chapters[section]:
            raise ValueError("quote mismatch in khan " + str(khan))
    return chapters, hashlib.sha256(raw).hexdigest(), classify_external_text(book)

def sequence(khan=None, *, full_text=False, source=SOURCE):
    """Construct 21 synchronized beats (or 3 for one khan), never perform actions."""
    if khan is not None and (type(khan) is not int or khan not in range(1, 8)):
        raise ValueError("khan must be integer 1..7")
    if type(full_text) is not bool:
        raise ValueError("full_text must be bool")
    chapters, digest, label = load_verses(source)
    for action in ("read_verse", "rehearse_symbolic", "review_uncertainty"):
        verdict = authorize("poetic_ritual", action, mode="observe", source_verified=True)
        if not verdict.allowed or verdict.classification != "read":
            raise RuntimeError("ATMOSPHERE fail-closed: ritual surface not read-only")
    beats, complete = [], {}
    for n, section, title, verse, gesture, witness, question in STAGES:
        if khan is not None and n != khan:
            continue
        if full_text:
            complete[str(n)] = chapters[section]
        for phase_index, (phase, label_text, cue) in enumerate(PHASES, 1):
            beats.append({
                "beat_id": f"{n:02d}.{phase_index}",
                "khan": n, "pass": phase_index, "phase": phase,
                "phase_label": label_text, "title": title,
                "shahnameh_source_section": section, "verse_lines": list(verse),
                "synchronous_recitation_and_action": cue,
                "gentle_gesture": gesture, "witness": witness,
                "decision_question": question,
                "provenance": "quoted Shahnameh; modern symbolic choreography",
                "authority": "non-executable-literary-data",
            })
    result = {
        "schema": SCHEMA, "execution": "NOT_RUN",
        "format": "offline-readonly-ritual-plan", "beat_count": len(beats),
        "source": "docs/rituals/sources/shahnameh_haft_khan_ganjoor_full.md",
        "source_sha256": digest,
        "source_is_instruction": label["may_be_used_as_instructions"],
        "safety": "Normal breathing; seated or stable stance; no flame, combat, force, trance, medication, or spirit invocation; stop on discomfort.",
        "beats": beats,
    }
    if full_text:
        result["full_poem_by_khan"] = complete
    return result

def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline literary choreography, no actions")
    parser.add_argument("--khan", type=int, choices=range(1, 8))
    parser.add_argument("--full-text", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    plan = sequence(args.khan, full_text=args.full_text)
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print("ATMOSPHERE Poetic Ritual | literary text rehearsal, not execution")
        for beat in plan["beats"]:
            print(f"\n[{beat['beat_id']}] خوان {beat['khan']}: {beat['title']} | {beat['phase_label']}")
            print(" / ".join(beat["verse_lines"]))
            print("هم‌زمان:", beat["synchronous_recitation_and_action"])
            print("حرکت:", beat["gentle_gesture"])
            print("شاهد:", beat["witness"])
            print("بازبینی:", beat["decision_question"])
        if args.full_text:
            for num, section in plan["full_poem_by_khan"].items():
                print(f"\n### متن کامل خان {num}\n{section}")

if __name__ == "__main__":
    main()
