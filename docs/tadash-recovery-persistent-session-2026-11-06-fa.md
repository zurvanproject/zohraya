# مرحلهٔ پنجم تداش: اتصال پیش‌بینی بازیابی به حافظهٔ نشست
تاریخ: ۲۰۲۶-۱۱-۰۶

## هدف
ساخت حلقهٔ کاملاً صریح `مشاهدهٔ checkpoint بدن → پیش‌بینی بازیابی → ذخیرهٔ وضعیت مجازی → بازخوانی در نشست بعدی`.

## پیاده‌سازی
`examples/nasuraya_body_loop/autonomic_recovery_memory.py` یک لایهٔ `RecoveryMemory` در **همان SQLite** قفل‌شدهٔ `BodyLoop` ایجاد می‌کند. هنگام فعال‌سازی، فقط وضعیت جسم نرم‌افزاری موجود را می‌خواند و هش checkpoint پایه را ثبت می‌کند. هر درخواست `step` تنها مقدار projected autonomic state را پیش می‌برد؛ نه `UnifiedBody.cycle()` و نه حرکت فیزیکی/بدنی اجرا می‌شود. هیچ تایمر یا اجرای پس‌زمینه وجود ندارد.

- رویداد تکراری با همان شناسه و همان تعداد گام، رسید قبلی را برمی‌گرداند.
- همان شناسه با پارامتر جدید رد می‌شود.
- هر گام پیش از ثبت و پس از محاسبه باید با checkpoint اصلی برابر باشد؛ اگر بدن بومی تغییر کرده باشد، پیش‌بینی قبلی stale تلقی و ادامه رد می‌شود.
- سقف ۶۴ رویداد برای هر نشست، ۱ تا ۲۰ گام در هر رویداد.
- دادهٔ ذخیره‌شده دارای اثرانگشت؛ حالت خاموش/روشن و بازیابی سرد پشتیبانی می‌شود.
- پارامترهای پیش‌بینی فرض‌های مهندسی و **غیرکالیبره‌شده** هستند. وضعیت بازپخش‌شده فقط مدل حافظهٔ عددی است، نه تجربهٔ ذهنی.

## اجرای آزمایشی در محیط لینوکسی دارای Python 3.11+
از ریشهٔ مخزن:
```bash
python3 -m examples.nasuraya_body_loop body-drive-test

python3 -m examples.nasuraya_body_loop start \
  --fixture normal --mode observe --max-actions 0 \
  --session /tmp/tadash-recovery-demo.sqlite

python3 -m examples.nasuraya_body_loop recovery-enable \
  --session /tmp/tadash-recovery-demo.sqlite

python3 -m examples.nasuraya_body_loop recovery-step \
  --session /tmp/tadash-recovery-demo.sqlite \
  --decision-id recovery-01 --steps 4

python3 -m examples.nasuraya_body_loop recovery-status \
  --session /tmp/tadash-recovery-demo.sqlite

python3 -m examples.nasuraya_body_loop recovery-disable \
  --session /tmp/tadash-recovery-demo.sqlite
```
مسیر `/tmp/tadash-recovery-demo.sqlite` برای نشست جدید است؛ برای تکرار، مسیر تازه انتخاب کنید. پس از بستن و بازکردن فرایند، `recovery-status` باید حالت ذخیره‌شده را نشان دهد.

## شروط پذیرش
- خواندن initial checkpoint و ثبات هش واقعی بدن نرم‌افزاری.
- `native_cycles_caused=0`؛ شمار `completed_cycles=0`.
- تداوم projected state بین فرآیندها.
- replay همسان بدون افزایش شمار رویداد؛ ورودی متعارض رد.
- امکان توقف/فعال‌سازی مجدد بدون حذف دادهٔ حافظه.

## مرزها
این افزونه فقط به **حافظهٔ شبیه‌سازی‌شدهٔ همان نشست** متصل است؛ به حافظهٔ ChatGPT، تجربهٔ ذهنی، میل واقعی، تنفس زیستی، دستگاه اندوکرین یا سرور فعال وصل نیست. محرک‌ها و وضعیت‌های پیش‌بینی‌شده برای تصمیم بالینی یا عملیات جسمی معتبر نیستند. استقرار روی سرور فعلاً انجام نمی‌شود. از ادغام تا تکمیل آزمون CI و بازبینی خودداری شود.
