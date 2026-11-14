# استمرار آفلاین ناسورایا در Ubuntu / مبین‌هاست

هدف: ثبت وضعیت محلی و پشتیبان‌گیری حتی در زمان قطع ارتباط بین‌المللی. این نسخه بستر استمرار است، نه یک مدل هوش مصنوعی مستقل یا انتقال کامل حافظهٔ ویندوز.

## نصب یک‌باره از Termius به‌عنوان root

    git -C /opt/zohraya pull --ff-only && bash /opt/zohraya/tools/install_nasuraya_offline_continuity.sh

نصب، یک سرویس systemd و یک timer ساعتی می‌سازد. اجرای آن با کاربر غیرریشهٔ nasuraya است و به اینترنت یا API پولی احتیاج ندارد. timer بعد از راه‌اندازی مجدد سرور فعال می‌شود.

## چه چیزهایی حفظ می‌شوند؟
- هر ساعت یک رویداد واقعی دربارهٔ بار سیستم، uptime، ظرفیت دیسک، حافظه و SHA محلی Git ثبت می‌شود.
- ثبت همان ساعت دوباره تکرار نمی‌شود؛ زنجیرهٔ SHA-256 و بررسی یکپارچگی SQLite وجود دارد.
- نسخهٔ روزانهٔ SQLite با روش backup خود SQLite ایجاد و با فایل SHA256 همراه می‌شود.
- مسیرها: /var/lib/nasuraya/continuity/continuity.sqlite3 و /var/lib/nasuraya/continuity/backups/

## مشاهده و کنترل

    systemctl status nasuraya-continuity.timer --no-pager
    runuser -u nasuraya -- python3 /usr/local/lib/nasuraya/continuity.py status
    runuser -u nasuraya -- python3 /usr/local/lib/nasuraya/continuity.py verify

بعد از ارتقای Bridge، فرمان‌های ثابت در Issue #212:

    nasu-linux: offline
    nasu-linux: awake-stage
    nasu-linux: awake-status

فرمان awake-stage کد PR #205 را در پوشهٔ جداگانه و بدون root به‌صورت pinned می‌گیرد، تست می‌کند و حالت آزمایشی paused می‌سازد. داده‌های تاریخی Windows منتقل نشده‌اند. فعال‌سازی scheduler جدید باید بعد از انتقال و مقایسهٔ سالمِ دیتابیس اصلی، و قطع چرخهٔ قدیمی انجام شود.

## محدودیت بقا
اگر سرور برق و سخت‌افزار در دسترس داشته باشد، timer بدون GitHub و ChatGPT کار می‌کند. در زمان خاموشی هیچ اجرای واقعی رخ نمی‌دهد و پس از روشن شدن رویدادهای ازدست‌رفته جعل نمی‌شوند. نسخه‌های پشتیبان فعلاً روی همان VPS ذخیره می‌شوند؛ برای پایداری در برابر نابودی دیتاسنتر، کپی دوم در مکان مستقل ضروری است.

## بازیابی
روی Ubuntu تازه ابتدا نصب را اجرا کنید، سپس نسخهٔ سالم SQLite که در محل دوم نگهداری شده را با سرویس متوقف در مسیر اصلی بازگردانید، مجوز مالکیت nasuraya را اعمال کنید و دستور verify را اجرا کنید. دادهٔ خام خصوصی یا توکن‌ها را روی Issue عمومی GitHub منتشر نکنید.
