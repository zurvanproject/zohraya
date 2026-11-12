# DIOS NOUS | پیش‌ثبت نوبت سوم، ۱۲ نوامبر ۲۰۲۶

## نقطهٔ شروع و محدوده
- PR: https://github.com/zurvanproject/zohraya/pull/192، باز و Draft، base=feature/dios-nous-dialogue-v01-20261109 (PR #176).
- head پیش از این نوبت: `ab83a14904b2c2ff129b593e4ccb03be32b2de70`؛ آخرین کد آزموده‌شده در نوبت ۲: `c7b910b4d09e2592ef028383eb7560c2940e8aba` و CI https://github.com/zurvanproject/zohraya/actions/runs/43145105912 با 55/55 آزمون موفق.
- فایل‌ها و workflow بازخوانی شدند. `.github/workflows/dios-nous-dialogue.yml` فقط `unittest` مربوط به `examples/dios_nous/**` و demo محلی را با `checkout@v4` و `setup-python@v5` در Ubuntu اجرا می‌کند؛ اجرای سرور، بدن، API مدل یا پولی در workflow نیست. اجرای CI نه شواهد مستقل انسانی است و نه مجوز اقدام.
- نقص متمرکز این نوبت: در `review_decision` وقتی `unqualified_claim=true` باشد، `supporting_evidence_present=true` از طرف همان فراخواننده هشدار `unsupported_certainty` را بدون بررسی مستقل حذف می‌کند. خوداظهاری شاهد، اعتبار مستقل نیست. مشکل قبلی `explicit_authorization_present` در نوبت ۱ اصلاح و در نوبت ۲ یکپارچگی رسید بررسی شد؛ دوباره کاری نمی‌شود.
- هدف این نوبت تنها ممیزی ادعاهای شاهد/عدم‌قطعیت و مقاومت در برابر ورودی‌های نامعتبر در همان لایهٔ مشورتی است. منشأ قضاوت به‌تنهایی سبب تغییر نتیجه نباشد.

## معیارهای پذیرش پیش از تغییر کد
1. اگر `unqualified_claim=true` باشد، `supporting_evidence_present` حتی با مقدار true نباید علامت بررسی `unsupported_certainty` را خاموش کند. وضعیت فقط `PROVISIONAL_DISSENT` است، نه اثبات بی‌پشتوانگی ادعا.
2. مقدار `supporting_evidence_present` با نام `supporting_evidence_claimed_by_caller` در خروجی بازتاب یابد، ولی `supporting_evidence_verification_status` در حالت ادعای قطعیت `UNVERIFIED` بماند؛ این مدل هیچ شاهدی را اصالت‌سنجی نمی‌کند.
3. بدون `unqualified_claim=true` و بدون نگرانی ثبت‌شده، هیچ مخالفت ساختگی تولید نشود، چه supporting-evidence true/false/غایب باشد.
4. همان ورودی و شواهد برای user/developer/system/platform/agent/external_service نتیجهٔ یکسان بدهد. ادعای مجوز/حریم خصوصی و قاعدهٔ `HALT_AND_REVIEW` نوبت‌های قبل تغییر نکنند.
5. دفتر SQLite گزارش ساختگیِ `supporting_evidence_verification_status=VERIFIED` یا برچسب متناقض با خروجی را نپذیرد؛ ورودی‌های مخدوشِ `origin`، `concern` و `provenance` کنترل‌شده رد شوند و هیچ رکورد ناقصی نوشته نشود.
6. تمام آزمون‌های ۵۵گانهٔ قبل و آزمون‌های تازه در CI دقیقِ commit کد پاس شوند، demo موفق باشد. شکست/صف به‌عنوان قبولی ثبت نشود. حداکثر ۶ فایل کد و ۳۰۰ خط تغییر؛ هیچ merge/deploy، سرور، سرویس یا API خارجی.

## محدودیت‌های تفسیر
پرچم `unqualified_claim` نیز گزارشِ فراخواننده است؛ بدون استخراج یا گواهی مستقل، مدل نمی‌تواند وجود/عدم وجود واقعیت را کشف کند. این اصلاح تنها **از پاک‌شدن ساکتِ پرچم بررسی با یک boolean خوداظهاری جلوگیری می‌کند**. خروجی مشورتی است، نه اجازهٔ اقدام یا اثبات استقلال/آگاهی.
