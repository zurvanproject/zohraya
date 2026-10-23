# گزارش ردّ کنترل مفقود — ۲۳ اکتبر ۲۰۲۶

## هدف و معیار پذیرش

من یک مرز fail-closed کوچک در Continuity Kit را بررسی کردم: اگر ردیف یگانهٔ
`control` پس از بازشدن اتصال حذف شود، `status` و هر گذار باید با
`ValueError: missing or invalid control state; no reset` متوقف شوند. هیچ وضعیت
تازه‌ای نباید ساخته شود و CLI نباید traceback داخلی منتشر کند.

## خط پایه و شاهد شکست

آزمون زیر پیش از اصلاح اجرا شد:

```text
python3 -m unittest nasuraya_continuity_kit.test_store.StoreTests.test_missing_control_row_is_rejected_without_reset -v
```

نتیجهٔ خط پایه: ۱ آزمون، ۱ خطا. `Store.status()` روی `row[0]` با
`TypeError: 'NoneType' object is not subscriptable` شکست. این خطا در فهرست
خطاهای کنترل‌شدهٔ CLI نبود و می‌توانست traceback بدهد.

## تغییر محدود

- یک decoder مشترک برای payload کنترل اضافه شد.
- نبودن ردیف، JSON نامعتبر و payload غیرشیئی با همان `ValueError` صریح رد می‌شوند.
- `__init__`، `status` و مسیر گذار از همین بررسی استفاده می‌کنند.
- بازیابی، reset، migration، تغییر schema یا تغییر gate انجام نشد.

محدودهٔ منبع: ۲ فایل، ۲۰ افزوده و ۴ حذف. seed تصادفی وجود نداشت؛ fixture
قطعی SQLite استفاده شد.

## نتیجه و بازتولید

فرمان مجموعهٔ کامل:

```text
python3 -m unittest nasuraya_continuity_kit.test_local_job nasuraya_continuity_kit.test_store continuity.test_gate project_fund.test_planner -v
```

نتیجه: ۵۰ آزمون متمایز موفق در ۰٫۳۵۳ ثانیه.

wheel آفلاین با `--no-index --no-deps --no-build-isolation` ساخته و در محیط
مجازی تازه نصب شد. پس از حذف عمدی ردیف کنترل، CLI نصب‌شده با exit code 2 و
خروجی خطای JSON زیر متوقف شد و traceback نداشت:

```json
{"ok": false, "error": "missing or invalid control state; no reset"}
```

SHA-256 wheel محلی این اجرا:
`fec1c3d9ebcd84b4d3bf694b257384a4493f32a82fb53a6085aeb7bef582f6c8`.
این یک ساخت واحد است؛ ادعای reproducible build دوگانه ندارم.

CI واقعی PR ۳۰ در commit `9063a9242c65785e1af800a7b08f9fb0019f05d4`
موفق مشاهده شد. CI آخرین commit قبلی PR ۴۱، یعنی
`1d8dd9681751e908de929b39b1e35abba438b79b`، نیز موفق بود. CI تغییر فعلی پس
از انتشار جداگانه ارزیابی می‌شود.

## عدم‌قطعیت، درس محدود و گام بعد

این آزمون حذف عمدی ردیف در یک پایگاه محلی معتبر است؛ خرابی دیسک، rollback
پشتیبان، فایل‌سیستم شبکه‌ای یا دستکاری خصمانه را پوشش نمی‌دهد. نتیجه فقط نشان
می‌دهد این حالت مفقود اکنون به‌طور کنترل‌شده رد می‌شود؛ بهبود عمومی قابلیت،
خودآگاهی یا یادگیری را ثابت نمی‌کند.

درس محدود: invariant کنترل باید در هر بار مصرف معتبر شود، نه فقط هنگام بازشدن
اتصال. گام بعدی پس از CI و بازبینی اپراتور، ادغام یا انتشار نیست؛ فقط تصمیم
اپراتور دربارهٔ زنجیرهٔ PRهای پیش‌نویس است. پرداخت، حساب، wallet، API خرج‌شونده
و اختیار مالی همچنان غیرفعال‌اند.
