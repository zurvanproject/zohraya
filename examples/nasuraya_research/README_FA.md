# مشاهده‌گر پژوهشی حداقلی

این بسته از `main` در commit `50780d88e1e95e7fc19037db4dd6a0227fcb204d`
جدا شده است. تابع `observe_native_body` فقط روی نمونهٔ از پیش ساخته‌شدهٔ بدن
فراخوانی می‌شود؛ هیچ زمان‌بند، چرخهٔ حرکت، اتصال API، یادگیری یا ذخیرهٔ وضعیت
خصوصی را فعال نمی‌کند.

```python
from examples.nasuraya_research.body_observer import observe_native_body

# body: نمونهٔ موجود UnifiedBody متعلق به فراخواننده
report = observe_native_body(body)
```

خروجی پایه شامل شش متغیر داخلی و شش مختصات پا در شبیه‌ساز است. این خروجی
بازسازی حسیِ PredVLA، پیش‌بینی آینده یا مشاهدهٔ جهان فیزیکی نیست.

گزینه‌ها:

- `decisions`: فقط ردیف‌های نتیجهٔ صریح با `correct: bool` و
  `keep_withdraw: KEEP | WITHDRAW`؛ آمار MMB، بدون اجرای تصمیم.
- `events`: رخدادهای محلی کامل‌شده برای تصویرسازی مسیر RoboRSI؛ نتیجهٔ
  ناشناخته یا هزینهٔ نامعلوم به نتیجه یا هزینهٔ ساختگی تبدیل نمی‌شود.
- `include_geometry=True` و `frame_yaw_rad`: تبدیل مختصات با زیرمجموعهٔ
  ریاضی mjlab/Isaac Lab؛ به وابستگی اختیاری CPU نیاز دارد. مدل فیزیک یا
  کنترل حرکت اجرا نمی‌شود. نبود این وابستگی خطا می‌دهد و نتیجهٔ جایگزین نمی‌سازد.

`native_snapshot.py` فقط تابع خواندن `snapshot` را از ماژول خودمدلِ شاخهٔ
پژوهشی جدا می‌کند؛ اعتبارسنجی checkpoint و `assess` موجود در `main` حفظ شده‌اند.
هیچ SelfModel یا پایگاه SQLite جدیدی لازم نیست.

```bash
# فقط کتابخانهٔ استاندارد: سه آزمون هندسه عمداً skip می‌شوند
python -S -m unittest examples.nasuraya_research.test_adapters examples.nasuraya_research.test_body_observer -v

# در محیط اختیاری با وابستگی‌های requirements-cpu.txt: بدون skip
python -m unittest examples.nasuraya_research.test_adapters examples.nasuraya_research.test_body_observer -v

# رگرسیون بدن و تصمیم، روی کپی موقتِ منابع تأییدشده
python runtimes/tadash_body/run_tests.py --reflection --output /tmp/research-observer-native
python -m examples.nasuraya_body_loop test
```

آزمون‌های این بسته فقط در درخت موقت، defaults مصنوعی می‌سازند. مشاهده‌گر
checkpoint را قبل و بعد مقایسه می‌کند؛ این بررسی حتی در خطای ابزار انجام
می‌شود. این سازوکار **تشخیص تغییر** است، نه sandbox، قفل هم‌زمانی یا rollback
در برابر کد مخرب. فراخوانی هم‌زمان نویسندهٔ بدن در این قرارداد آزمایش نشده است.

شش ورودی قفل‌شدهٔ upstream از سه پروژه عیناً حفظ شده‌اند. اعلان BSD اضافی
نیز hash ثابت دارد. قفل جدید فقط به این بسته تعلق دارد؛ manifestها و
سیاست‌های امنیتی موجود `main` تغییر نمی‌کنند.

تنها گردش‌کار افزوده، آزمون استاندارد همین مشاهده‌گر و رگرسیون موجود است؛
هیچ گردش‌کار قبلی، schedule، secret یا مجوز نوشتنی عوض نشده است. آزمون هندسه
فعلاً محلی تأیید شده و در job استاندارد به‌صورت صریح skip می‌شود.

جزئیات وابستگی، شواهد و مراحل ادغام در
[گزارش جداسازی](../../docs/nasuraya-research-minimal-integration-2026-10-18-fa.md) است.

## اختیار اجرایی اختیاری

مشاهده‌گر اصلی همچنان خواندنی است. ماژول جداگانهٔ `controller` می‌تواند
پس از فعال‌سازی صریح، مشاهده را به درخواست محدود در BodyLoop وصل کند.
هر نشستِ این نسخه حداکثر سه اقدام دارد و از بودجه، دفتر تصمیم، قفل و
نگهبان‌های موجود استفاده می‌کند. انتخاب اولیه از `assess` موجود می‌آید؛
هستهٔ تصمیم و بدن همچنان می‌توانند آن را عوض یا رد کنند.

```bash
# یک نشست تازهٔ کاملاً مصنوعی؛ مسیر موجود بازنشانی نمی‌شود
python -m examples.nasuraya_research.control init --session /tmp/research-body.sqlite --fixture normal --max-actions 3
# مشاهده، انتخاب و اجرای حداکثر دو چرخهٔ شبیه‌سازی
python -m examples.nasuraya_research.control run --session /tmp/research-body.sqlite --steps 2
python -m examples.nasuraya_research.control pause --session /tmp/research-body.sqlite
python -m examples.nasuraya_research.control status --session /tmp/research-body.sqlite
# ازسرگیری صریح؛ بودجه را افزایش نمی‌دهد
python -m examples.nasuraya_research.control resume --session /tmp/research-body.sqlite
# درخواست نام‌دار برای بازخوانی نتیجه بدون تکرار اثر
python -m examples.nasuraya_research.control step --session /tmp/research-body.sqlite --request-id final
# آزمون‌ها در فرایند جدا با منابع native تأییدشده
python -S -m examples.nasuraya_research.control test
```

چرخه‌ها فقط `walk` یا `observe` درخواست می‌کنند؛ زمان هر چرخه ۰٫۱ تا ۱
ثانیهٔ شبیه‌سازی است. درخواست نامعلوم خودکار تکرار نمی‌شود. توقف و بودجه
در SQLite باقی می‌مانند و شروع دوباره آن‌ها را پر نمی‌کند. نشست دارای بودجهٔ
اولیهٔ بیش از سه اقدام به این اختیار پذیرفته نمی‌شود. این لایه برنامهٔ
همیشه‌روشن، کنترل جسم فیزیکی یا اختیار شبکه/پول/API ایجاد نمی‌کند.

گزارش و حدود اجرای تازه در
[اختیار محدود](../../docs/nasuraya-research-authority-v01-fa.md) ثبت شده است.

## سنجش اختیاریِ اعتماد

برای ثبت پیش‌بینی پیش از اجرا و اصلاح گزارش اعتماد از روی رسیدهای همین نشست،
به [قرارداد توکل و کالیبراسیون](../../docs/nasuraya-research-confidence-v01-fa.md)
رجوع کنید. در نشست تازه، `control init --forecast-confidence .75` این قابلیت
را با prior اعلام‌شده فعال می‌کند. `control evaluate` آزمایش مصنوعیِ محدود
و کنترل جابه‌جایی guard را اجرا می‌کند. این عدد، معیار اخلاقی یا مجوز عمل نیست.

برای آزمون انتقال به وضعیت‌های تازه با آموزش ثابت، دستور `control transfer
--output-dir /tmp/new-transfer` و گزارش
[آزمون انتقال](../../docs/nasuraya-frozen-transfer-v01-fa.md) در دسترس است.
نتایج آزمون به حافظهٔ تولیدی وارد نمی‌شوند؛ `control transfer-test` پروتکل را
جداگانه می‌آزماید و `control test` همهٔ آزمون‌های این مسیر را اجرا می‌کند.
