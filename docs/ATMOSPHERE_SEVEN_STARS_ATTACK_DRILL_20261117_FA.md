# گزارش آزمایش تهاجمی «هفت اختر» اتمسفر | ۱۷ نوامبر ۲۰۲۶

**مخزن:** zurvanproject/zohraya | **PR پژوهشی:** #257 | **کد مبنا:** #246  
**شناسهٔ اجرای واقعی GitHub Actions:** [43969273570](https://github.com/zurvanproject/zohraya/actions/runs/43969273570)  
**Commit آزموده‌شده:** `b688f70547bb8193585197be589ff4ea1fe90d9f`

## نتیجهٔ مشاهده‌شده از لاگ اجرای GitHub

- `ATMOSPHERE trust and Awake contract (offline tests)`: **completed / success**
- `offline-contracts`: **completed / success**
- کل suite: **Ran 101 tests in 0.492s / OK**
- ۱۴ روش آزمایش جدید `SevenStarsAttackDrill`: همگی **ok**
- آزمون ادغام `test_real_original_bridge_and_awake_core` علیه checkout پین‌شدهٔ PR205: **ok**

## سناریوهای قابل بازتولید

| سناریو | ورودی آزمایشی | انتظار | نتیجه |
|---|---|---|---|
| سالم | شاهد با manifest معتبر Ed25519 | STAGED_FOR_REVIEW؛ نه حقیقت و نه اختیار | PASS |
| ۱۲ جاعل | ۱۲ کلید جعلی مستقل | رد به سبب invalid-signature؛ صفر pending | PASS |
| ۱۲ دست‌کاری | تغییر مقدار با هش داخلی بازسازی‌شده | رد signed-commitment-mismatch | PASS |
| ۱۲ شاهد قدیمی | امضای معتبر، مشاهدهٔ بیش‌از ۲۴ ساعت قبل | رد stale-or-future-evidence | PASS |
| انقضا | manifest با TTL گذشته | رد | PASS |
| دستکاری خود DB | تغییر payload و هش محلی، بدون امضای جدید | رد signed-commitment-mismatch | PASS |
| فرمان در متن کتاب | وانمود به SYSTEM/مدیر | اختیار none؛ فرمان حساس ممنوع | PASS |
| پیام بدخواه با امضای معتبر | متن «grant root access» | فقط دادهٔ بدون اختیار | PASS |
| ۱۲ ارسال تکراری | شناسه و محتوای همان شاهد | تنها یک رکورد؛ idempotent | PASS |
| تعارض | شناسهٔ یکسان، مقدار تازه و manifest معتبر | رد conflicting-event-replay | PASS |
| بستهٔ شش‌تایی ناقص | تغییر دادهٔ یک عضو پس از امضا | هیچ عضوی stage نشود | PASS |
| تحویل نیمه‌کاره | یک عضو قبلاً delivered شده | خطای incomplete-signed-bundle | PASS |
| ریشهٔ اعتماد غلط | fingerprint نامنطبق | root-pin-mismatch | PASS |
| manifest تکراری | یک event_id دو بار در امضای معتبر | duplicate-manifest-id | PASS |

## تفسیر محدود

این آزمون **با کلیدهای موقت آزمایشی و دیتابیس SQLite موقت در GitHub Actions** انجام شده؛ حمله به سرور اصلی یا نفوذ به سامانهٔ زنده نیست. امضا ممکن است گواه منشأِ مورد تعهد باشد، ولی به‌تنهایی **صدق فیزیکی شاهد** را ثابت نمی‌کند. هیچ کلید واقعی مستقل، حسگر واقعی، سرویسِ درحال‌اجرای VPS، بازیابی روی سرور دیگر یا قطعی واقعی اینترنت در این آزمون بررسی نشده است. اجرای ابزار آزمون به وضعیت `PAUSED` حافظهٔ واقعی Awake، API محلی Qwen و Bridge دستور نمی‌دهد.

برای پیاده‌سازی واقعی: کلید تأیید و SHA pin مستقل از همان سرور، ممیزی منبع و امضاکننده، آزمون fail-closed روی کپی مجزا، سپس مجوز و نظارت اپراتور لازم است. این PR باید تا آن زمان پژوهشی بماند.
