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


## اتصال واقعیِ پژوهشی v0.2: حس + DIOS + هدف → Awake

این پیوند **یک‌طرفه، فقط‌خواندنی و مستقل از VPS** است. کد bridge.py خروجی
اصلی `Session.snapshot()` در PR #198 را از نسخهٔ دقیق
`d86750d8d26d4ea6a3fe595f9e1ee81e95d81fec` می‌خواند. موتور اصلی
واقعاً حس عددی، حافظهٔ حسی، ارزیابی DIOS، هدفِ موجود و رسید کنش شبیه‌سازی را
تولید می‌کند. پل فقط شش فیلد scalar مجاز را به SQLite دفتر Awake منتقل می‌کند:

- sensory_load / prediction_error / sensory_occurrence
- goal_selected / dios_sensory_stance / action_matches

پل پیش از واردکردن، SHA-256 محتوای snapshot، هش دوبارهٔ حس در receipt،
منشأ نسخهٔ مدل، revision و فعال‌بودن هدف را تطبیق می‌دهد. این‌ها آزمون
**سازگاری داخلی** هستند نه امضای امنیتی یا اثبات راست‌بودن حس. ورودی باید
از checkout معتمد تولید شده باشد. پارامتر `stream` برای هر نشست واقعی
باید یکتا و ثابت انتخاب شود؛ بازپخش یک مشاهده با همان زمان `observed_at`
بی‌اثر است و مقدار متفاوت با همان شناسه، اتمی رد می‌شود.

موتور سؤال‌سازی در تابع `propose` بین دو مشاهدهٔ ناهم‌زمان و اختلاف
واقعی هم‌زمان تمایز اولیه می‌گذارد. برای نشست شبیه‌سازی ساعت
`sample_time` برحسب ثانیه استفاده می‌شود؛ برای منابع قدیمی UTC.
اختلاف زمانیِ مقدار سؤال `temporal_change` می‌سازد، نه ادعای تناقض.
ساعت‌های مخلوط و نامقایسه‌پذیر `time_scope_uncertain` می‌شوند.
پنجرهٔ ۰٫۱۱ ثانیه برای شبیه‌سازی و ۶۰ ثانیه برای ساعت دیواری
**فرضیه‌های مهندسی** هستند، نه کالیبراسیون حسگر.

### آزمایش بازتولیدپذیر

GitHub Actions در Windows و Linux ابتدا آزمون‌های محلی را اجرا می‌کند، سپس
checkout مستقل PR #198 را روی SHA ثابت انجام می‌دهد، یک نشست واقعی
`Session.create` و دو عمل `Session.step` با ورودی عددی اجرا می‌کند،
نشست را می‌بندد و دوباره می‌گشاید و دو snapshot را به SQLite Awake
وارد می‌کند. دو tick مستقل از هم باید سؤال را حفظ کنند و تغییر زمانی را
از ناسازگاری هم‌زمان جدا کنند. نتیجهٔ CI و رسید آن باید بررسی شود؛
نوشتن این دستورالعمل به معنی موفقیت آزمون نیست.

برای import یک snapshot حاصل از کد معتمد، پس از بازبینی:

```powershell
python -m tadash_awake.bridge --root C:\Nasuraya\Awake --snapshot C:\Temp\snapshot.json --stream unique_session_001 --observed-at 2026-11-13T09:00:00Z
python -m tadash_awake resume --root C:\Nasuraya\Awake
python -m tadash_awake tick --root C:\Nasuraya\Awake
python -m tadash_awake status --root C:\Nasuraya\Awake
```

زمان `observed-at` در بازپخش همان snapshot باید بدون تغییر بماند.
هیچ دادهٔ خام بیمار، متن خصوصی، token، shell، مدل پولی، انتشار Moltbook،
تغییر main یا فرمان Bridge وارد این اتصال نمی‌شود. هدفِ منتقل‌شده همان
هدف authored در DIOS است، نه یک «آرزوی خودآفریده» اثبات‌شده. پرسش‌های
منتخب Awake گام‌های پژوهشی قابل‌پیگیری‌اند و به کنش خارجی تبدیل نمی‌شوند.

**محدودیت عمده:** اتصال از طریق خروجی snapshot اجرا می‌شود و هنوز
sensor ingress خودکار روی VPS، زمان‌بندی نصب‌شده، یا اتصال دوطرفهٔ
Awake به تصمیم‌گیری زندهٔ تداش نیست. ادغام وابستگی‌ها و استقرار باید
جداگانه بررسی شود.
