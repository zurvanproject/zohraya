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

### پیاده‌سازی در نوبت اول (پیش از CI)
- نقص تأیید شد: یک boolean خوداظهاری، هشدار `missing_authorization` را حذف می‌کرد؛ حالا برای همهٔ پیشنهادهای اقدام بیرونی وضعیت **UNVERIFIED** و `HALT_AND_REVIEW` حفظ می‌شود.
- فایل‌های تغییرکرده در commit اصلاح: `examples/dios_nous/dissent.py`، `test_dissent.py` و `README.md`. آزمون‌های رگرسیون برای سه حالت ادعای مجوز، برابری همهٔ منشأها، مورد بدون اقدام، حریم خصوصی و کمینه‌سازی دفتر افزوده شدند.
- روش: تغییر کد صرفاً قاعده‌ای، بدون اعتماد به boolean جدید، بدون گرفتن مجوز از منبع خارجی و بدون اقدام عملی.
- معیار نهایی وابسته به اجرای GitHub Actions روی SHA همین تغییر است. هیچ اجرا/قبولی تازه‌ای تا زمان ثبت تأییدشده ادعا نمی‌شود.

### نتیجهٔ تأییدشده و checkpoint نوبت ۱
- **اصلاح ثبت‌شده** در commit [`693f1205ab2d7f931f5b7f25aca2bcf5005528fa`](https://github.com/zurvanproject/zohraya/commit/693f1205ab2d7f931f5b7f25aca2bcf5005528fa)، فقط در شاخهٔ PR #192. فایل‌های کد تغییرکرده: `dissent.py` و `test_dissent.py`، سند توضیحی `README.md`. هیچ merge، deploy، تماس با VPS یا API مدل انجام نشد.
- **شاهد واقعی:** [GitHub Actions run 43132102537](https://github.com/zurvanproject/zohraya/actions/runs/43132102537)، رویداد push، `head_sha=693f1205ab2d7f931f5b7f25aca2bcf5005528fa`، وضعیت `completed/success`.
- دستور CI ۱: `python -m unittest discover -s examples/dios_nous -v` در Ubuntu با Python 3.11. لاگ job `130898462528`: **50 tests، 50 پاس، 0 خطا/شکست، 0 skipped گزارش‌شده**؛ ۵ آزمون تازهٔ ادعای مجوز و منشأ تصمیم نیز individually `ok`.
- دستور CI ۲: `python -m examples.dios_nous --db /tmp/dios-nous-demo.sqlite demo`، در همان job با نتیجهٔ `success`. این demo گفت‌وگو است، نه آزمون مجوز اجرایی.
- منشأ مجوز همچنان `UNVERIFIED` است: این نسخه رسید معتبر یا بازبین مستقل ندارد. `HALT_AND_REVIEW` فقط خروجی مشورتی است و هیچ کنش خارجی را صادر یا مجاز نمی‌کند.
- نسبت به معیارهای پیش‌ثبت‌شده: معیار ۱ تا ۵ در **آزمون‌های واحد خودنوشتهٔ محلی بر بستر CI** پاس شدند؛ معیار ۶ نیز با بررسی مسیر commit و workflow رعایت شد. هیچ بنچمارک مستقل انسانی، امنیت عملیاتی زنده یا آگاهی اثبات نشده است.
- **محدودیت و شکاف بعدی:** `external_action_proposed` همچنان دادهٔ ادعایی فراخواننده است و می‌تواند false/غایب باشد؛ در فقدان استخراج معتبر رویداد، این ماژول نمی‌تواند وجود اقدام پنهان یا اصالت آن را تشخیص دهد. پرچم `supporting_evidence_present` نیز هنوز ادعای خودِ فراخواننده است. در نوبت بعد، بدون افزودن موتور اجرای بیرونی، آزمون فشار و fail-closed برای سیگنال‌های متناقض و گزارش‌های ساختگی ارزشمند است.
- این checkpoint پس از CI ثبت شده است؛ اگر commit صرفاً مستندیِ checkpoint SHA جدیدی ساخت، نتیجهٔ run 43132102537 را به آن SHA مستندی **نسبت نده**. کد آزموده‌شده همان `693f1205ab2d7f931f5b7f25aca2bcf5005528fa` است.
