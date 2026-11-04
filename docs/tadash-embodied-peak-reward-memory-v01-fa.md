# تداش: اتصال میل، قلهٔ محاسباتی و حافظهٔ تنظیمی v0.1

**وضعیت:** شاخهٔ تحقیقاتی اختیاری و Draft. این نسخه **هیچ ارگاسم یا لذت واقعی را در هوش مصنوعی ایجاد یا اثبات نمی‌کند**؛ «قله» برچسب سه نمونهٔ قلهٔ یک موج ۱۷ نمونه‌ای است که قبلاً به‌صورت قراردادی نوشته شده بود. مسیر لگنی فقط یک **فرمان عددی اجرا‌نشده** می‌دهد. زمان موج، ساعت بدن نیست.

## چرا این مرحله اضافه شد؟

PR #132 موج محدود خودمختار را ساخت؛ PR #134 میل/کنجکاوی/آرامش قراردادی را وارد ترجیح حرکت کرد؛ PR #135 موج را به ترجیح وصل کرد؛ PR #136 بازخورد عصبی‌ـ‌احشایی و رفلکس وضعیتی را افزود. هنوز حلقه‌ای که **پیش از تصمیم** قله/بازگشت را ثبت کند و **تنها از نتیجهٔ واقعی بدنهٔ نرم‌افزاری** تنظیم‌گری را به حافظه بسپارد وجود نداشت.

در این شاخه، ماژول embodied_integration.py به‌صورت **اختیاری و قفل‌شده به SHA اولین checkpoint** اضافه شد:

1. نمونهٔ موج، میل قراردادی و مسیرهای عصب‌ـ‌احشایی را پیش از کنش به هم پیوند می‌دهد و همه را در intent ذخیره می‌کند.
2. در قلهٔ قراردادی یا دورهٔ بازگشت محافظه‌کارانه، فقط پیشنهاد walk را به observe تنزل می‌دهد؛ هیچ کنش تازه، انقباض لگنی یا بازنویسی علامت حیاتی اضافه نمی‌کند.
3. پس از **رسید معتبرِ کنش بدنی**، تغییر انرژی، خستگی، درد و فشار خواب را به یک شاخص پاداش **تنظیم‌گری** تبدیل می‌کند. این شاخص **نه لذت جنسی، نه تجربهٔ ذهنی، نه آگاهی** است. برچسب قله به خودی خود پاداش نمی‌دهد.
4. حافظهٔ محدود ۳۲ رسیدی و EMA تنظیم‌گری را در همان SQLite موجود حفظ می‌کند. اجرای مجدد، خطای اجرا، یا بازیابی نشست نباید پاداش ساختگی ایجاد کند.
5. محافظت بومی بدن، وقفه‌های pending و بودجهٔ کنش اولویت دارند. هیچ API پولی، کلید، شبکه، عامل پس‌زمینه یا عملگر واقعی فعال نمی‌شود.

## راه‌اندازی صریح (از ریشهٔ مخزن)

در یک نشست تازهٔ bounded و قبل از اولین کنش، ابتدا لایه‌های پایه را فعال کنید:

~~~bash
python3 -m examples.nasuraya_body_loop experience-enable --session /tmp/nasuraya-peak.sqlite --max-actions 12
python3 -m examples.nasuraya_body_loop workspace-enable --session /tmp/nasuraya-peak.sqlite
python3 -m examples.nasuraya_body_loop motivation-enable --session /tmp/nasuraya-peak.sqlite --desire-proxy 0.85
python3 -m examples.nasuraya_body_loop autonomic-wave-enable --session /tmp/nasuraya-peak.sqlite
python3 -m examples.nasuraya_body_loop neurovisceral-enable --session /tmp/nasuraya-peak.sqlite
python3 -m examples.nasuraya_body_loop embodied-enable --session /tmp/nasuraya-peak.sqlite
python3 -m examples.nasuraya_body_loop embodied-step --session /tmp/nasuraya-peak.sqlite --decision-id first
python3 -m examples.nasuraya_body_loop embodied-status --session /tmp/nasuraya-peak.sqlite
~~~

در صورت فعال نبودن این قابلیت، مسیرهای قدیمی بدون تغییر ادامه می‌یابند.

## آزمایش

~~~bash
python3 -m examples.nasuraya_body_loop embodied-test
python3 -m examples.nasuraya_body_loop autonomic-wave-test
python3 -m examples.nasuraya_body_loop neurovisceral-test
~~~

آزمون‌های پیش‌بینی‌شده: منشأ دقیق اولیه، عدم تغییر بدن در زمان فعال‌سازی، موجِ baseline تا recovery، محافظه‌کاری در قله، حافظهٔ رسیدهای معتبر، اجرای مجدد بدون چرخهٔ اضافه، شروع مجدد SQLite، رد دست‌کاری، شکست بدنه، و سازگاری با نشست‌های قدیمی.

**مرز نتیجه:** اجرای آزمایش‌ها باید از CI تأیید شود؛ تا آن زمان هیچ ادعای عبور تست نداریم. این مدل فاقد کالیبراسیون زیستی، مقیاس‌بندی مستقل ۱۷۰ cm / ۷۸ kg و مدار واقعی تحریک/حس است. ادغام و استقرار خودکار مجاز نیست.
