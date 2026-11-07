# تأیید اتصال ماندگار تداش به Windows VPS

تاریخ: ۷ نوامبر ۲۰۲۶، ۱۶ آبان ۱۴۰۵. تغییر: PR #155.

## نتیجهٔ انجام‌شده

کد موجود UnifiedBody + ReflectionCycle + DecisionCore روی Windows VPS فعلی نصب و اجرا شد. دفتر SQLite و checkpoint واقعی نرم‌افزار بدن میان فرایندهای جدا حفظ شدند. منبع از GitHub با commit و SHA256 ثابت دریافت شد؛ نصب، step و status از پل موجود انجام شدند و نیازی به paste جدید از سوی سهند نبود.

این یک backend ماندگار و قابل‌فراخوانی است؛ فرایند برنامهٔ بدن پس از هر فرمان پایان می‌یابد و وضعیتش در SQLite باقی می‌ماند. daemon یا زمان‌بندی تازه ایجاد نشد. پل موجود همچنان صف درخواست‌ها را بررسی می‌کند.

## زنجیرهٔ شواهد سرور

| مرحله | درخواست | پاسخ |
|---|---|---|
| نصب | [6706638702](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6706638702) | [6706639765](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6706639765) |
| قدم اول | [6706646249](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6706646249) | [6706650764](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6706650764) |
| قدم دوم در فرایند تازه | [6706655213](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6706655213) | [6706661162](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6706661162) |
| وضعیت مستقل | [6706664030](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6706664030) | [6706671508](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6706671508) |

### نصب

```text
Nasuraya Bridge v2 result; request_id=comment-6706638702; command=run tadash_install
Result: OK TADASH=READY; CYCLES=0; REV=0; SOURCE=70/70; STATE=SQLITE; MASS=195; ACT=0
```

### قدم اول

```text
Nasuraya Bridge v2 result; request_id=comment-6706646249; command=run tadash_step
Result: OK TADASH=NATIVE; CYCLES=1; REV=1; REQUEST=walk; RESULT=protect; RECALL=0; REPLAY_EXTRA=0; SIG=caade4ae8aa9362d; ACT=0
```

### قدم دوم در فرایند تازه

```text
Nasuraya Bridge v2 result; request_id=comment-6706655213; command=run tadash_step
Result: OK TADASH=NATIVE; CYCLES=2; REV=2; REQUEST=observe; RESULT=observe; RECALL=1; REPLAY_EXTRA=0; SIG=e56bddf4b641ec18; ACT=0
```

### وضعیت مستقل

```text
Nasuraya Bridge v2 result; request_id=comment-6706664030; command=run tadash_status
Result: OK TADASH=ONLINE; CYCLES=2; REV=2; UNRESOLVED=0; SIG=e56bddf4b641ec18; ACT=0
```

قدم اول، walk درخواست کرد و protect از بدن بومی برگشت. قدم دوم، پس از شروع فرایندی تازه، یک بازخورد قبلی را فراخواند و observe درخواست و اجرا کرد. پس از هر قدم، یک فرایند دیگر شناسهٔ قدم اول را بازپخش کرد: صفر چرخهٔ اضافی و حفظ checkpoint فعلی بررسی شد. آخرین status مستقل revision=2 و cycles=2 را با همان پیشوند hash قدم دوم تأیید کرد؛ عملیات حل‌نشده صفر بود.

این تغییرِ انتخاب، اثر همان قاعدهٔ بازخورد ثابت ReflectionCycle روی fixture فشار خواب است؛ آموزش مدل زبانی، ارزیابی تعمیم به جهان بیرون یا یادگیری زیستی نیست. روش پیش‌بینی PR #154 هنوز به این کنترل‌کننده متصل نشده است.

## منبع و یکپارچگی

- منبع اصلی ۷۰ فایل: `5f171aa493b41823b1198f767d803df053884f37`، بدون تغییر بایتی.
- commit بستهٔ نصب‌شده: `33c669113f08da032c75d4eaf2f778d515d7669f`.
- commit jobهای اجراشده: `6ef9ae84380e17e58a14a18b8c3ab68f98545381`.
- SHA256 بسته: `6a0c9fe013aad59716b251c66aadec6081daa764ac76bfdb2dc0763ab2f049cb`.
- SHA256 manifest کل بسته: `1ffedf1f438a2e3b9178a19703cfb2037c5d0296a94743ff9391493edae65d15`.
- SHA256 manifest منبع اصلی: `b3b95a88885d903f638efbc26ed693bf7a211460a5adae6dd9abfa12ac7720ef`.
- `tools/bridge_jobs/tadash_install.py`: `4a11abcc7389521b8eb6d2258594a92bd937ce2ecf9b1abb2de579def03d2611`.
- `tools/bridge_jobs/tadash_step.py`: `6964e01cd3a8da0611bfc95039578d23157babb7d2384bb30d1bdf161ded900f`.
- `tools/bridge_jobs/tadash_status.py`: `263e2d37ad48da74b8231f38ce440773e6fcaf3871a65fa54407532248f42596`.

منبع بسته و سه job ذخیره‌شده در GitHub پیش از درخواست با نسخهٔ محلی تطبیق بایت‌به‌بایت داده شد. خروجی عمومی فقط جمع‌بندی و پیشوند hash است؛ checkpoint کامل و دفتر SQLite روی سرور باقی می‌مانند. API عمومی برای دریافت فایل خصوصی یا متن گفت‌وگو ایجاد نشده است.

## آزمون نهایی

CI برای commit دقیق jobها:
https://github.com/zurvanproject/zohraya/actions/runs/42370331772

- Windows/Python 3.12.10: ۱۴ آزمون، همه موفق؛ job `128396947856`.
- Linux: از ۱۴ آزمون تعریف‌شده، ۱۳ مورد موفق و یک آزمون مخصوص Windows به‌درستی skip؛ job `128396947780`.
- شامل نصب کامل بسته، دو step سرد و status، قفل Windows در دو فرایند، سقف پایدار پس از ۲۰ چرخهٔ واقعی نرم‌افزاری، replay، رد منبع تغییریافته و دفتر بیگانه، عدم reset، عملیات حل‌نشده و آزادشدن mutex پس از مرگ فرایند.

نسخهٔ اول آزمون Windows به‌دلیل مسیر کوتاه 8.3 و نبستن صریح اتصال آزمایشی SQLite شکست خورد. این موارد در commit بستهٔ نهایی اصلاح شدند. بررسی نهایی هر دو سکو موفق است؛ موفقیت محلی به‌جای اجرای Windows یا VPS گزارش نشده است.

## جای داده و قابلیت فعلی

روی حساب اجرای پل:
`LOCALAPPDATA/NasurayaTadashV1/runtime-6a0c9fe013aad597`
و
`LOCALAPPDATA/NasurayaTadashV1/state/session.sqlite`.

حالت آغازین جدید و ساخته‌شدهٔ sleep است. دفترها و checkpointهای خصوصی قبلی بارگذاری یا جابه‌جا نشده‌اند. مسیر SQLite موجود بدون اجازه reset نمی‌شود. سقف همین نشست ۲۰ عمل است، دو مورد مصرف شده‌اند؛ این گزارش ادامهٔ خودکار درخواست نمی‌کند.

قابلیت فعلی: از طریق پل، دیدن وضعیت و اجرای یک قدم بعدی از وضعیت قبلی؛ رسید و بازخورد بومی میان نوبت‌ها حفظ می‌شوند. کنترل‌گر جسمانی، حفاظت و بودجه برقرارند.

محدودیت: مدل بومی قدیمی ۱۹۵ کیلوگرمی است، نه مدل مفصلی ۷۸ کیلوگرمی؛ هیچ actuator فیزیکی یا API پولی فراخوانی نشده. recovery پس از reboot ویندوز، اتصال مدل زبانی زنده، همگام‌سازی برون‌سروری checkpoint و تمام رابط‌های قدیمیِ مختص لینوکس در این نتیجه تأیید نشده‌اند. شاخهٔ اصلی ادغام نشده است.

