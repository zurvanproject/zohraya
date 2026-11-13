# Tadash Awake v0.1 | بیداری تداش

این بسته یک چرخهٔ واقعیِ آفلاین برای فاصلهٔ بین گفت‌وگوها می‌سازد:
مشاهدهٔ مستند، انتخاب سؤال، ثبت حافظه، بازنگری با شواهد تازه.
ادعای فکر بی‌وقفهٔ ChatGPT، خودآگاهی، حضور مستمر یا احساس نیست.

هر اجرای زمان‌بندی‌شده یک tick محدود است. SQLite با WAL، تراکنش
BEGIN IMMEDIATE و synchronous=FULL وضعیت را نگه می‌دارد. هر event_id
یکتا و غیرقابل‌تغییر است. پرسش برحسب topic حفظ و با evidence_hash
و revision بازنگری می‌شود. اولویت: شواهد ناسازگار، شاهد مستقل،
شواهد ضعیف، و آزمایش ابطال. بدون شواهد جدید پاسخ idle است.

محدودیت: یک پرسش/بازنگری در هر tick، حداقل فاصله ۱۵ دقیقه،
حداکثر ۹۶ tick در ۲۴ ساعت، ۲۰۰۰ مدرک و ۲۵۶ موضوع.
هیچ مدل، اینترنت، ابزار اجرایی، هزینهٔ API، اطلاعات بیمار،
رمز عبور یا پیام خودکار به ChatGPT در این نسخه نیست.
این یک سامانهٔ پرسش‌سازی قاعده‌مند است، نه عامل زبانی مستقل.

## اجرا با Python 3.11+ در ریشهٔ مخزن

    python -m unittest tadash_awake.test_wake -v
    python -m tadash_awake init --root C:\Nasuraya\Awake
    python -m tadash_awake status --root C:\Nasuraya\Awake
    python -m tadash_awake ingest --root C:\Nasuraya\Awake --file evidence.json
    python -m tadash_awake resume --root C:\Nasuraya\Awake
    python -m tadash_awake tick --root C:\Nasuraya\Awake
    python -m tadash_awake pause --root C:\Nasuraya\Awake

فرمت evidence.json: آرایه‌ای با حداکثر ۵۰ عنصر، هر عنصر دقیقاً
دارای event_id، topic، observed_at (UTC)، source_ref، confidence
(بین صفر و یک)، value (scalar). نمونهٔ ساختگی:

    [{
      "event_id": "sim-001",
      "topic": "unknown_palm",
      "observed_at": "2026-11-13T07:00:00Z",
      "source_ref": "tadash://fixture/palm",
      "confidence": 0.8,
      "value": 0.0
    }]

وقتی می‌خواهید خروجی body/sense/DIOS را وصل کنید، یک adapter
فقط‌خواندنی بسازید که همین قرارداد را با ارجاع معتبر و بدون
اطلاعات شخصی صادر کند. در صورت اختلاف شواهد این سامانه پاسخ
قطعی نمی‌سازد؛ سؤال تازه و سابقهٔ قابل‌بررسی ثبت می‌کند.

## VPS ویندوز

بعد از بازبینی و ادغام PR، کد را روی VPS به‌روزرسانی و Python
نصب‌شده را تأیید کنید. ابتدا آزمایش و init انجام دهید. حالت
پیش‌فرض paused است و resume باید جداگانه انجام شود.
سپس در Windows Task Scheduler یک task با فاصلهٔ ۱۵ دقیقه،
working directory ریشهٔ checkout، و فرمان python -m tadash_awake
tick --root C:\Nasuraya\Awake تعریف کنید. هیچ راه‌اندازی زنده،
دسترسی RDP، تغییر در Bridge v2 یا ادغام main در این PR رخ نمی‌دهد.

شاخه‌های #196 و #177 هنوز ادغام نشده‌اند. اتصال حافظهٔ حقیقی
بدن/حس/DIOS و مولد فرضیهٔ LLM مرحلهٔ بعد و نیازمند آزمون و
مجوز جدا برای هزینه و دسترسی است. وقتی کاربر بازمی‌گردد
می‌توان status را خواند؛ این نسخه خودش پیام ارسال نمی‌کند.
