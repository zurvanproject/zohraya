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
