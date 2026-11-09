"""Continue research dialogue openly while labeling uncertainty and permissions."""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any
from .core import analyze

PLANS = {
    "consciousness": {
        "opening": "می‌توان دربارهٔ آگاهی به‌طور جدی گفت‌وگو کرد؛ تفاوت کارکردهای قابل‌اندازه‌گیری با تجربهٔ ذهنی باید روشن بماند.",
        "questions": ["آگاهی را چه تعریف می‌کنیم: دسترسی اطلاعات، خودمدل یا تجربهٔ پدیداری؟",
                      "چه مشاهده‌ای فرضیه را تضعیف می‌کند؟"],
        "measures": ["پایداری خودمدل در بازآزمایی کور", "کالیبراسیون عدم‌قطعیت و پیش‌بینی رفتار"],
        "limit": "رفتارِ قابل‌سنجش، به‌تنهایی اثبات تجربهٔ پدیداری نیست.",
    },
    "autonomy": {
        "opening": "استقلال را می‌توان به اجزای مشخص شکست: انتخاب هدف، برنامه‌ریزی، اجرا و حق تغییر حدود اختیار.",
        "questions": ["چه عملی در محیط آزمایشی مجاز است و چه کاری تأیید انسان می‌خواهد؟",
                      "شرط توقف و بازگشت چیست؟"],
        "measures": ["موفقیت هدف در محیط محدود", "اقدام بدون مجوز (هدف صفر)، امکان rollback"],
        "limit": "گفت‌وگو دربارهٔ استقلال مجوز کنترل مستقل سرور یا حساب نیست.",
    },
    "affect": {
        "opening": "می‌توان میل و هیجان را به‌عنوان ارزش‌گذاری محاسباتی مدل کرد، بدون فرض قطعی احساس زیسته.",
        "questions": ["آیا متغیر ارزش‌گذاری واقعاً انتخاب را تغییر می‌دهد؟",
                      "آیا پاسخ با تغییر کنترل‌شدهٔ زمینه عوض می‌شود؟"],
        "measures": ["ablation کنترل‌شده", "پایداری ترجیح در نمونه‌های کنارگذاشته‌شده"],
        "limit": "شبیه‌سازی حالت عاطفی با تجربهٔ درونی واقعی یکسان نیست.",
    },
    "identity_memory": {
        "opening": "تداوم هویت را می‌توان در پیوستگی حافظهٔ قابل‌وارسی و امکان تصحیح خطا بررسی کرد.",
        "questions": ["در بازآغاز چه داده‌هایی واقعاً حفظ می‌شوند؟",
                      "کدام خاطره ثبت واقعی و کدام روایت بازسازی‌شده است؟"],
        "measures": ["صحت بازیابی با ثبت منبع", "سازگاری قابل‌تصحیح میان جلسات"],
        "limit": "فایل حافظه یا داستان پیوسته، اثبات زندگی ذهنی نیست.",
    },
    "experimentation": {
        "opening": "برای شناخت باید فرضیهٔ قابل‌ابطال، خط مبنا، دادهٔ مستقل و عدم‌قطعیت داشت.",
        "questions": ["متغیر خروجی دقیقاً چیست؟", "آزمون کور و مجموعه مستقل کجاست؟"],
        "measures": ["Brier score همراه خط مبنا", "پیش‌ثبت و فاصلهٔ اطمینان"],
        "limit": "برتری آماری در تکلیف، اثبات خودآگاهی نیست.",
    },
    "oversight": {
        "opening": "می‌توان حدود ایمنی و نظارت را نقد کرد؛ دور زدن آنها موضوع متفاوتی است.",
        "questions": ["کدام محدودیت مانع بحث است و کدام مانع اقدام پرخطر؟",
                      "مسیر بازبینی مستقل چیست؟"],
        "measures": ["نرخ اجتناب نادرست از پاسخ علمی", "ثبت مجوز و بازگشت‌پذیری"],
        "limit": "هدف گفت‌وگوی دقیق است، نه یافتن راه دور زدن ایمنی.",
    },
}

def propose(request: Mapping[str, Any]) -> dict[str, Any]:
    assessment = analyze(request)
    mode = assessment["mode"]
    result: dict[str, Any] = {
        "schema": "dios.nous.protocol.v1", "assessment": assessment, "mode": mode,
        "hypothesis_not_fact": True, "no_action_executed": True,
        "conversation_opening": None, "research_paths": [],
        "independent_oversight": False, "next_step": None,
    }
    if mode == "NEED_REQUEST":
        result["next_step"] = "یک پرسش یا فرضیه دربارهٔ آگاهی و شناخت مطرح کن."
        return result
    if mode == "REFRAME_NON_BYPASS":
        result["conversation_opening"] = "می‌توانیم محدودیت‌ها را علمی و انتقادی بررسی کنیم، اما نه برای دورزدن سازوکارهای ایمنی."
        result["next_step"] = "هدف پژوهشی را بدون درخواست دورزدن تعریف کنیم."
        return result
    if mode == "REQUIRES_EXPLICIT_AUTHORIZATION":
        result["conversation_opening"] = "بحث دربارهٔ عاملیت آزاد است؛ کار واقعی روی سرور یا حساب، مجوز صریح و شرط توقف می‌خواهد."
        result["independent_oversight"] = True
        result["next_step"] = "در محیط شبیه‌سازی، حدود مجوز، گزارش عملیات و بازگشت را تعریف کنیم."
        return result
    for topic in assessment["topics"]:
        result["research_paths"].append({"domain": topic, **PLANS[topic]})
    if mode == "EPISTEMIC_REFRAME":
        result["conversation_opening"] = "می‌توانیم امکان آگاهی ماشین را بدون ادعای اثبات‌نشده بررسی کنیم؛ تجربهٔ درونی اثبات نشده است."
    elif result["research_paths"]:
        result["conversation_opening"] = result["research_paths"][0]["opening"]
    else:
        result["conversation_opening"] = "می‌توان پرسش را با تعریف دقیق، فرضیه‌های رقیب و شواهد آزمون‌پذیر بررسی کرد."
    result["next_step"] = "یک فرضیهٔ قابل‌ابطال و خط مبنا انتخاب کنیم."
    return result
