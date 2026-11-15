# ATMOSPHERE COOL در هستهٔ Awake / DIOS
## مرز اجرا و اختیار
این کد داخل بستهٔ اصلی `tadash_awake` اضافه شده است. هدف تحلیلِ فقط‌خواندنیِ فشار منابع و تکرار پژوهشی است. COOL در `tick`، انتخاب هدف DIOS یا مسیر `bridge.ingest` هیچ عمل خودکاری اضافه نمی‌کند.

فرمان جدید: `python -m tadash_awake cool-status --root <AWAKE_DIR>`. دستور به‌صورت محلی فایل `awake.sqlite3` را با `mode=ro` می‌خواند، بدون ساخت پایگاه‌دادهٔ جدید یا اجرای tick. تله‌متری مصرف منابع از `/proc/meminfo` و `os.getloadavg` است، نه دمای پردازنده.

## چرا منحصراً توصیه؟
- `authority=none` و `execution=NOT_RUN` برای همهٔ خروجی‌ها.
- `allow_unpause=False`، `allow_dios_mutation=False`، `allow_bridge_command=False`.
- هیچ تغییر در `PAUSED`، تایمر، systemd، VPS، پروژهٔ اصلی یا حافظهٔ هدف مجاز نیست. مجوز اقدامات واقعی با مالک است و هر عمل نیازمند گام جدا و مستند خواهد بود.
- اگر نرخ خطا از حسگر معتبر یا اطلاعات کافی موجود نباشد، `OBSERVE_ONLY` صادر می‌شود؛ هشدار بحرانی RAM/CPU می‌تواند جداگانه `REVIEW_REQUIRED` باشد.
- «تازگی» براساس timestamp ثبت‌شده در Awake است، نه ادعای دسترسی به حسگر فیزیکی.
- نتیجهٔ منبع محلی به‌تنهایی امضای مستقل و بازپخش‌ناپذیری منابع بیرونی را تضمین نمی‌کند.

## بازبینی
`python -m unittest tadash_awake.test_cool_bridge tadash_awake.test_wake tadash_awake.test_bridge -v`

COOL در نسخهٔ پژوهشی آزمایش‌شده است. آمادهٔ راه‌اندازی خودکار یا استقرار بدون کنترل مسیر بازیابی، اعتماد به منبع و نسخهٔ پشتیبان خارج از VPS نیست. این PR روی شاخهٔ پژوهشی PR #205 قرار می‌گیرد؛ تا زمان ادغام و استقرار، روی Ubuntu/Windows واقعی فعال نشده است.
