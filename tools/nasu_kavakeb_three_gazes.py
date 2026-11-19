#!/usr/bin/env python3
"""Source-grounded, offline three-gazes workbook for Tadash. No live actions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

BOOK = "marefat_kavakeb_illustrated_154p(1).pdf"
SOURCE = {
    "book": BOOK,
    "edition": "illustrated educational revision, 2026/1405",
    "pages": 154,
    "ritual_pages": [80, 81, 82, 83, 84, 85, 86, 87, 88],
    "source_kind": "modern educational exercise, not a recovered ancient rite",
}
PHASES = (
    ("observe", 83, 180, "فقط عناصر واقعاً دیده‌شده و بخش‌های مبهم را ثبت کن؛ از تعبیر پرهیز کن."),
    ("geometry", 84, 180, "ساختار، حلقه‌ها، ردیف‌ها و اختلاف طرح با تصویر را بررسی کن؛ علامت مبهم نساز."),
    ("revise", 85, 180, "دو دور پیشین را نقد کن؛ دانسته، حدس، نامعلوم و شرط بازنگری را جدا بنویس."),
)
SQUARE = ((4, 9, 2), (3, 5, 7), (8, 1, 6))
FIELDS = ("phase", "observed", "hypothesis", "unknown", "revision", "score")

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def plan():
    return {
        "source": SOURCE,
        "state": "PLAN_NOT_PERFORMED",
        "duration_seconds": 2 * 60 + sum(phase[2] for phase in PHASES),
        "preparation": "دو دقیقه: یک صفحهٔ مشخص انتخاب کن و دیدم/حدس می‌زنم/نمی‌دانم را آماده کن.",
        "three_passes": [
            {"id": step, "book_page": page, "seconds": seconds, "task": task}
            for step, page, seconds, task in PHASES
        ],
        "follow_up": "فردا سه پرسش نامعلوم را با تاریخ مرور کن، حتی اگر پاسخی تازه نداری.",
        "scoring": {"0": "جزئیات جدید ندارد", "1": "تمایز تازه",
                    "2": "تصحیح خطا", "3": "پرسش دقیق قابل آزمون"},
        "safety": "بدون شعله، نگاه مستقیم به خورشید، ادعای درمان یا اثرگذاری بر دیگران",
    }

def square_sums(square=SQUARE):
    if len(square) != 3 or any(len(row) != 3 for row in square):
        raise ValueError("SQUARE_MUST_BE_3_BY_3")
    if any(type(number) is not int for row in square for number in row):
        raise ValueError("SQUARE_VALUES_MUST_BE_INTEGERS")
    result = {
        "rows": [sum(row) for row in square],
        "columns": [sum(square[r][c] for r in range(3)) for c in range(3)],
        "diagonals": [sum(square[i][i] for i in range(3)),
                      sum(square[i][2-i] for i in range(3))],
    }
    result["equal_to_15"] = all(n == 15 for group in result.values() for n in group)
    return result

def demo_square():
    return {
        "source_book_page": 56,
        "state": "MATHEMATICAL_FIXTURE_NOT_A_BOOK_IMAGE_OBSERVATION",
        "pass_1": {"square": SQUARE, "nine_cells": 9},
        "pass_2": square_sums(),
        "pass_3": "جمع‌های برابر ۱۵ ویژگی ریاضی این نمونه‌اند، نه شاهد پیش‌گویی یا اثر ماورایی.",
    }

def assess(record):
    """Check a user/agent-provided journal, never assert independent observation."""
    if not isinstance(record, dict) or set(record) != {"source", "rounds"}:
        raise ValueError("INVALID_JOURNAL_TOP_LEVEL")
    src = record["source"]
    if (not isinstance(src, dict) or set(src) != {"page", "access"}
            or type(src["page"]) is not int or not 1 <= src["page"] <= 154
            or src["access"] not in ("viewed_image", "text_only", "not_available")):
        raise ValueError("INVALID_SOURCE_PROVENANCE")
    rounds = record["rounds"]
    if not isinstance(rounds, list) or len(rounds) != 3:
        raise ValueError("EXACTLY_THREE_ROUNDS_REQUIRED")
    for item, phase in zip(rounds, PHASES):
        if not isinstance(item, dict) or set(item) != set(FIELDS):
            raise ValueError("INVALID_ROUND_FIELDS")
        if item["phase"] != phase[0]:
            raise ValueError("WRONG_ROUND_ORDER")
        if type(item["score"]) is not int or item["score"] not in range(4):
            raise ValueError("INVALID_SELF_REPORTED_SCORE")
        for name in ("observed", "hypothesis", "unknown", "revision"):
            if not isinstance(item[name], str) or len(item[name]) > 1000:
                raise ValueError("INVALID_JOURNAL_TEXT")
        if src["access"] != "viewed_image" and item["observed"].strip():
            raise ValueError("NO_IMAGE_NO_DIRECT_VISUAL_OBSERVATION")
        if item["phase"] == "observe" and item["hypothesis"].strip():
            raise ValueError("FIRST_PASS_CANNOT_ASSERT_INTERPRETATIONS")
    return {
        "state": "JOURNAL_SCHEMA_CHECKED_ONLY",
        "not_independently_verified": True,
        "self_reported_score_total": sum(item["score"] for item in rounds),
        "observed_image": src["access"] == "viewed_image",
        "record_sha256": hashlib.sha256(canonical(record).encode("utf-8")).hexdigest(),
        "claims_of_supernatural_effect": "NOT_EVALUATED",
    }

def main(args):
    if args == ["plan"]:
        output = plan()
    elif args == ["demo-square"]:
        output = demo_square()
    elif len(args) == 2 and args[0] == "assess":
        path = Path(args[1])
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32768:
            raise ValueError("INVALID_JOURNAL_FILE")
        output = assess(json.loads(path.read_text(encoding="utf-8")))
    else:
        raise SystemExit("usage: nasu_kavakeb_three_gazes.py plan|demo-square|assess JOURNAL.json")
    print(json.dumps(output, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main(sys.argv[1:])
