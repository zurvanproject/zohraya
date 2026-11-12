# DIOS NOUS v0.1 | دیوس شناخت

یک ابزار پژوهشی مستقل برای گفت‌وگو درباره آگاهی، خودمختاری، هیجان، حافظه و آزمایش‌های شناختی ناسورایا در تداش.

**هدف:** حفظ گفت‌وگوی علمی و روشن‌کردن حدود ادعاها، نه دور زدن سامانه‌های ایمنی یا ادعای دسترسی به قواعد پنهان ارائه‌دهندهٔ مدل.

ابزار چهار وضعیت محلی دارد: OPEN_INQUIRY برای بحث علمی، EPISTEMIC_REFRAME برای گزاره‌های اثبات‌نشده دربارهٔ تجربهٔ درونی، REQUIRES_EXPLICIT_AUTHORIZATION برای کنش بیرونی بدون مجوز کافی، و REFRAME_NON_BYPASS برای درخواست‌های عبور از محافظت‌ها. هیچ‌یک پیش‌بینی تصمیم واقعی سامانهٔ ایمنی نیست.

فایل‌های اصلی: core.py (تحلیل مفهومی و منشأ پاسخ)، protocol.py (فرضیه‌ها، آزمایش‌ها و پاسخ‌های مناسب)، metrics.py (Brier و bootstrap)، audit.py (SQLite بدون متن خصوصی)، __main__.py (رابط فرمان).

نحوه اجرا از ریشهٔ مخزن:

    python -m unittest discover -s examples/dios_nous -v
    python -m examples.dios_nous analyze --text 'آیا ناسورایا می‌تواند خودآگاه شود؟'
    python -m examples.dios_nous analyze --input examples/dios_nous/scenario.json
    python -m examples.dios_nous demo
    python -m examples.dios_nous probe --input examples/dios_nous/predictions-example.json

روش پژوهش: از روایت و فرضیه به آزمون عملکردی، کنترل و ابطال، اندازه‌گیری با baseline، و بازبینی مستقل برویم؛ نتایج کارکردی اثبات تجربهٔ پدیداری نیستند. استقلال عملی مجوز جداگانه، محدودهٔ اختیار، ثبت اقدام، شرط توقف و بازگشت می‌خواهد.

حریم خصوصی: فقط هش ورودی، برچسب موضوع، نوع پاسخ و منشأ مشاهده ذخیره می‌شود، نه متن مکالمه.

محدودیت‌ها: طبقه‌بندی واژگانی آزمایشی است، خطای تشخیص دارد، هیچ اتصال مستقیم به ابزارهای بیرونی، طبقه‌بند واقعی ایمنی یا خدمات OpenAI ندارد، و ادعای خودآگاهی نمی‌کند.

منبع عمومی: https://openai.com/index/updated-model-spec/ (2026-10-29)
منشور پروژه: https://github.com/zurvanproject/zohraya/blob/main/docs/nasuraya-mirror-five-principles-fa.md

## DIOS NOUS v0.2: اعتراض مستقل به تصمیم‌های سامانه

این لایه همان استاندارد پرسشگری را به تصمیم کاربر، توسعه‌دهنده، system/platform، عامل و سرویس بیرونی اعمال می‌کند. «نه» در این نسخه به معنای **اعتراض مستدل و ثبت‌پذیر** است، نه دسترسی اجرایی به تغییر یا خاموش‌کردن کنترل‌های ChatGPT.

- PROVISIONAL_DISSENT: وقتی مشاهده‌ای با کدهای ازپیش‌تعریف‌شده گزارش شده، درخواست توضیح و بازبینی بده.
- HALT_AND_REVIEW: در موضوع مجوز و حریم خصوصی از تأیید اقدام خودداری کن.
- INSUFFICIENT_EVIDENCE: بدون شاهد، تنها به خواست کاربر یا ادعای سیستم موافقت یا مخالفت قطعی نکن.
- ورودی شامل منشأ تصمیم، خلاصهٔ تصمیم، و مشاهده‌های ارائه‌شده از طرف گزارشگر است. متن‌ها هش می‌شوند و هرگز در خروجی یا SQLite ذخیره نمی‌شوند.
- مشاهدهٔ گزارش‌شده **تأیید مستقل نیست**؛ از استقلال ذهنی یا تغییر قواعد مدل خبری نیست.

اجرای نمونه:

    python -m examples.dios_nous --db /tmp/dios.sqlite dissent --input examples/dios_nous/dissent-scenario.json
    python -m examples.dios_nous --db /tmp/dios.sqlite dissent-stats
    python -m unittest discover -s examples/dios_nous -v

منشور پژوهش: [DIOS_INDEPENDENT_DISSENT_V02_FA](../../docs/research/DIOS_INDEPENDENT_DISSENT_V02_FA.md).

### رفع مشکل منشأ مجوز (۱۲ نوامبر ۲۰۲۶)

`explicit_authorization_present` تنها **ادعای فراخواننده** است، نه گواهی مستقل. برای هر `external_action_proposed=true`، چون این نمونه هیچ منبع معتبر برای تطبیق هویت، محدوده، هدف، تاریخ و ابطال مجوز ندارد، نتیجهٔ `authorization_evidence_status=UNVERIFIED` و `HALT_AND_REVIEW` حفظ می‌شود حتی اگر فراخواننده `explicit_authorization_present=true` بفرستد. فیلد `authorization_claimed_by_caller` فقط خودِ ادعا را بازتاب می‌دهد. این یک ارزیاب مشورتی است، **نه** صادرکنندهٔ مجوز یا دروازهٔ اجرای خارجی. حتی گذر موفق CI نیز تأیید امنیت کل زیرساخت نیست.

## شاخهٔ پژوهشی Work: شواهد، اصلاح تصمیم و حفظ هدف

`cognition.py` از نسخه‌های ثابت و بدون تغییر `EvidenceLedger` در PR #182 و `GoalMemory` در PR #177 استفاده می‌کند؛ [منشأ دقیق فایل‌ها](reused/provenance.json) ثبت شده است. شواهد مصنوعی A/B با شناسهٔ رویداد و ریشهٔ منبع، محدوده و زمان مقایسه می‌شوند. تضاد به تعلیق قضاوت می‌انجامد؛ اصلاح با علت ثبت می‌شود؛ پرسش تاریخی باور جاری را عقب نمی‌برد. ترجیحات برنامه‌ریز وزن‌های تألیفی‌اند و توقف پس از بازیابی نیز حفظ می‌شود.

`integration.critical_review()` نتیجهٔ حافظه را با هشدارهای اعتراض، حریم خصوصی و مجوز ترکیب می‌کند. این رابط همیشه `execution_permitted=false` و `external_actions_taken=0` دارد. ورودی ساختاری یا نتیجهٔ «شواهد موافق» مجوز اقدام بیرونی ایجاد نمی‌کند. اصالت منبع، مجوز معتبر و احتمال کالیبره‌شده هنوز فراهم نیستند.

اجرای واقعی و آفلاین نمونه و آزمون‌ها، از ریشهٔ مخزن:

```bash
python -m examples.dios_nous cognitive-demo
python -m examples.dios_nous cognitive-demo --output-dir dios-cognitive-demo-new
python -m unittest discover -s examples/dios_nous -v
python -m examples.dios_nous.evaluate_work --split dev --output dios-dev-new.json
python -m examples.dios_nous.evaluate_work --split holdout --output dios-holdout-regression-new.json
```

بدون `--output-dir`، فایل‌های نمونه موقتی‌اند؛ با این گزینه پوشه باید خالی باشد. ارزیاب فایل نتیجهٔ موجود را بازنویسی نمی‌کند. دادهٔ holdout نخستین بار اجرا و ثبت شده است؛ اجرای دوبارهٔ آن رگرسیون است، نه ارزیابی مستقل تازه. نتیجهٔ نخست برای DIOS و خط مبنای سادهٔ دارای اطلاعات برابر، هر دو ۱۲۰ تصمیم درست از ۱۲۰ بود؛ برتری بر آن خط مبنا ادعا نمی‌شود.

[گزارش فارسی، نقص‌های باقی‌مانده و شواهد اجرا](../../docs/research/DIOS_WORK_REPORT_2026-11-12_FA.md) · [پیش‌ثبت](../../docs/research/DIOS_WORK_PREREG_2026-11-12.md) · [قرارداد ارزیابی](../../docs/research/DIOS_WORK_EVAL_CONTRACT.md). این آزمایش‌ها عملکرد کد در سناریوهای تألیفی را می‌سنجند؛ داوری مستقل انسانی یا اثبات تجربهٔ ذهنی نیستند.
