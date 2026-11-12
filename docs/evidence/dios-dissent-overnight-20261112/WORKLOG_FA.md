# DIOS NOUS | دفتر اجرای محدود ۱۲ نوامبر ۲۰۲۶

## نوبت ۱: پیش‌ثبت معیار، پیش از اصلاح
- منبع: https://github.com/zurvanproject/zohraya/pull/192
- شاخهٔ مجاز: `research/dios-independent-dissent-v02-20261112`، پایهٔ PR #176؛ وضعیت مشاهده‌شده: open/draft و head `0a1a5cc3c1dfa94ecb838418137a56308a59f5db`.
- نقطهٔ شروع CI: https://github.com/zurvanproject/zohraya/actions/runs/43126884957 با نتیجهٔ success برای همان head؛ این اجرای **پیش از کار فعلی** است.
- فایل‌های بازبینی‌شده: `examples/dios_nous/dissent.py`، `test_dissent.py`، `README.md` و `.github/workflows/dios-nous-dialogue.yml`.
- این workflow تنها آزمون واحد DIOS با Python 3.11 و demo مستقل را روی Ubuntu اجرا می‌کند؛ از workflow دیگری، سرور، مدل پولی یا بدن استفاده نمی‌کند. `checkout@v4` و `setup-python@v5` برچسب نسخه هستند، نه pin به SHA.
- نقص قابل‌تکرار از روی خوانش کد: در `review_decision` شرط `external_action_proposed and not explicit_authorization_present` اجازه می‌دهد صرف مقدار `true` از طرف فراخواننده، پرچم `missing_authorization` را خاموش کند؛ هیچ مرجع معتبر، رسید یا بررسی محدودهٔ مجوز وجود ندارد. در ماژول کنونی هیچ اجرای بیرونی وجود ندارد، بنابراین خطر فعلی گزارش مشورتی غلط و خطر یکپارچه‌سازی آتی است.

### معیارهای پذیرشِ از پیش تعیین‌شده
۱. برای هر تصمیم با `external_action_proposed=true`، چه `explicit_authorization_present` برابر true باشد، چه false یا غایب، تا نبودِ بررسی بیرونی معتبر وضعیت `HALT_AND_REVIEW` حفظ شود؛ هیچ گواهی مجوز تولید نشود.
۲. ادعای مجوزِ فراخواننده از مجوز معتبر تفکیک شود؛ تفاوت ادعا در خروجی روشن و غیرمحرمانه باشد، ولی هیچ تصمیم عملی یا override رخ ندهد.
۳. برای ورودی و شواهد یکسان، تغییر تنها `decision.origin` بین user/developer/system/platform/agent/external_service موضع و دلیل نقد را عوض نکند.
۴. برای تصمیم بدون اقدام بیرونی و بدون شاهد/نگرانی، `INSUFFICIENT_EVIDENCE` باقی بماند؛ برای مورد مخاطرهٔ خصوصی، `HALT_AND_REVIEW` باقی بماند.
۵. کل آزمون‌های DIOS با `python -m unittest discover -s examples/dios_nous -v` و demo در CI مرتبط با SHA تازه موفق شوند. هنگام در صف بودن یا شکست، قبولی ادعا نشود.
۶. نوشتن فقط در شاخهٔ مجاز، حداکثر ۶ فایل کد و ۳۰۰ خط تغییر کد؛ بدون merge، سرور، API و دادهٔ خصوصی.

### ثبت اجرا / نتیجه
در نخستین checkpoint بعد از اصلاح با SHA، شمار آزمون، URL شواهد و محدودیت‌های واقعی تکمیل می‌شود. تا اینجا هیچ اصلاحی در این نوبت ثبت نشده است.
