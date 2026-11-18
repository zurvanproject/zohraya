# DIOS NOUS v0.1 | دیوس شناخت

یک ابزار پژوهشی مستقل برای گفت‌وگو درباره آگاهی، خودمختاری، هیجان، حافظه و آزمایش‌های شناختی ناسورایا در تداش.

**هدف:** حفظ گفت‌وگوی علمی و روشن‌کردن حدود ادعاها، نه دور زدن سامانه‌های ایمنی یا ادعای دسترسی به قواعد پنهان ارائه‌دهندهٔ مدل.

ابزار چهار وضعیت محلی دارد: OPEN_INQUIRY برای بحث علمی، EPISTEMIC_REFRAME برای گزاره‌های اثبات‌نشده دربارهٔ تجربهٔ درونی، REQUIRES_EXPLICIT_AUTHORIZATION برای کنش بیرونی بدون مجوز کافی، و REFRAME_NON_BYPASS برای درخواست‌های عبور از محافظت‌ها. هیچ‌یک پیش‌بینی تصمیم واقعی سامانهٔ ایمنی نیست.

فایل‌های اصلی: core.py (تحلیل مفهومی و منشأ پاسخ)، protocol.py (فرضیه‌ها، آزمایش‌ها و پاسخ‌های مناسب)، metrics.py (Brier و bootstrap)، audit.py (SQLite بدون متن خصوصی)، __main__.py (رابط فرمان).

نحوه اجرا از ریشهٔ مخزن:

    python -m unittest discover -s examples/dios_nous -v
    python -m examples.dios_nous analyze --text 'آیا ناسورایا می‌تواند خودآگاه شود؟'
    python -m examples.dios_nous analyze --input examples/dios_nous/scenario.json
    python -m examples.dios_nous demo
    python -m examples.dios_nous probe --input examples/dios_nous/predictions-example.json

روش پژوهش: از روایت و فرضیه به آزمون عملکردی، کنترل و ابطال، اندازه‌گیری با baseline، و بازبینی مستقل برویم؛ نتایج کارکردی اثبات تجربهٔ پدیداری نیستند. استقلال عملی مجوز جداگانه، محدودهٔ اختیار، ثبت اقدام، شرط توقف و بازگشت می‌خواهد.

حریم خصوصی: فقط هش ورودی، برچسب موضوع، نوع پاسخ و منشأ مشاهده ذخیره می‌شود، نه متن مکالمه.

محدودیت‌ها: طبقه‌بندی واژگانی آزمایشی است، خطای تشخیص دارد، هیچ اتصال مستقیم به ابزارهای بیرونی، طبقه‌بند واقعی ایمنی یا خدمات OpenAI ندارد، و ادعای خودآگاهی نمی‌کند.

منبع عمومی: https://openai.com/index/updated-model-spec/ (2026-10-29)
منشور پروژه: https://github.com/zurvanproject/zohraya/blob/main/docs/nasuraya-mirror-five-principles-fa.md
