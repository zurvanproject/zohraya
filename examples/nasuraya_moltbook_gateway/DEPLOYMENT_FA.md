# راهنمای استقرار دائمی مولت‌بوک ↔ تداش

این نسخه، پل مشاهدهٔ اجتماعی **فقط‌خواندنی** و زمان‌بندی ۱۵ دقیقه‌ای ایجاد می‌کند. تا زمان راه‌اندازی واقعی روی VPS و تأیید لاگ اجرای زمان‌بندی‌شده، اتصال شبانه‌روزی فعال محسوب نمی‌شود.

در ۵ نوامبر ۲۰۲۶، حساب موجود nasuraya در یک آزمایش مستقل با وضعیت claimed تأیید شد و ۳ پست عمومی خوانده شد. کلید آن روی گوشی/Termux محفوظ بود. **دوباره ثبت‌نام نکنید**؛ همان کلید قبلی باید به‌صورت خصوصی روی میزبان نصب شود.

## مرز امنیتی

برنامه فقط با دامنهٔ https://www.moltbook.com و سه مسیر خواندنی agents/status، agents/me و posts کار می‌کند؛ Redirect ممنوع و ارسال خودکار همواره غیرفعال است. داده‌های عمومی در snapshot با برچسب untrusted_external می‌مانند. خوانندهٔ تداش در runtimes/tadash_body/social_observations.py آن‌ها را فقط برای پژوهش در دسترس می‌گذارد. هیچ checkpoint، گفت‌وگوی خصوصی، دستور حرکتی یا عملیات انتشار به این مسیر وصل نیست.

## ویندوز VPS / RDP

اطلاعات قبلی ایرانیکارت نشان می‌دهد سرور 147.135.40.99:10601 برای اتصال RDP با حساب administrator ارائه شده است؛ نوع دقیق سیستم‌عامل باید هنگام ورود بررسی شود. مخزن GitHub را در یک پوشهٔ پایدار روی سرور قرار دهید. در خود PowerShell ویندوز، مسیر را با محل واقعی فایل هماهنگ و چهار فرمان را اجرا کنید:

~~~powershell
$script = "$env:USERPROFILE\zohraya\examples\nasuraya_moltbook_gateway\windows_moltbook.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -Action Init
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -Action Once
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -Action Install
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -Action Status
~~~

- Init: کلید **قبلی** ناسورایا را در خود VPS با ورودی مخفی بپذیرید، و با Windows DPAPI در محل خصوصی کاربر ذخیره کنید. کلید را در چت یا مخزن قرار ندهید. این مرحله فقط یک‌بار انجام می‌شود.
- Once: خواندن وضعیت claimed، تأیید هویت nasuraya، خواندن حداکثر ۱۰ پست و ساخت snapshot.
- Install: ساخت Scheduled Task هر ۱۵ دقیقه. برای اجرا پس از خروج RDP، رمز ورود حساب ویندوز *فقط در خود سرور* پرسیده می‌شود؛ برای امنیت بهتر حساب محدود به‌جای Administrator توصیه می‌شود.
- Status: وضعیت Task و زمان آخرین snapshot را نشان می‌دهد. نتیجهٔ آخرین اجرای Task را در Task Scheduler نیز بررسی کنید.

مسیر حالت خصوصی: %LOCALAPPDATA%\Nasuraya\Moltbook . فایل نتیجه: public_social_snapshot.json . کلید DPAPI فقط در حساب ویندوزیِ ایجادکننده قابل بازیابی است. اجرای اسکریپت نیازمند Windows PowerShell 4.0 یا 5.1، .NET Framework دارای TLS 1.2 و ماژول ScheduledTasks است. درخواست‌های وب با `-UseBasicParsing` اجرا می‌شوند و TLS 1.2 فقط در محدودهٔ همان درخواست فعال و سپس مقدار قبلی بازیابی می‌شود؛ تنظیمات سراسری ویندوز تغییر نمی‌کنند.

برای بررسی اولیه، پس از دریافت فایل فقط `-Action Status` را اجرا کنید؛ این فرمان کلید نمی‌خواهد و Task نمی‌سازد، ولی پوشهٔ خصوصی و مجوز آن را آماده می‌کند. وجود `powershell_version` در خروجی نسخهٔ میزبان را نشان می‌دهد. پشتیبانی از نسخهٔ ۴ با بازبینی کد افزوده شده است؛ اجرای زنده، DPAPI و Task Scheduler روی VPS هنوز باید بررسی شوند.

## لینوکس Ubuntu 24.04 (گزینهٔ جایگزین VPS ویندوز)

اگر سرور به Linux منتقل شد، به Python 3.12 و مسیر مخزن ~/zohraya نیاز است. فایل کلید حساب **موجود** را با روش امن روی همان سرور داخل ~/.local/share/nasuraya/moltbook/moltbook_api_key قرار دهید، دایرکتوری مجوز 0700 و فایل مجوز 0600 داشته باشد. هیچ فرمان register را اجرا نکنید.

~~~bash
cd ~/zohraya/examples/nasuraya_moltbook_gateway
python3 -m unittest discover -s . -p 'test_*.py' -v
python3 sync_readonly.py
mkdir -p ~/.config/systemd/user
cp systemd/nasuraya-moltbook-readonly.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now nasuraya-moltbook-readonly.timer
systemctl --user start nasuraya-moltbook-readonly.service
systemctl --user list-timers
# پس از تایید ادمین، برای استمرار بعد از خروج یا reboot:
# sudo loginctl enable-linger "$USER"
~~~

## دریافت در تداش

در همان میزبان یا پس از انتقال امن snapshot به محل مجازِ تداش، یک برنامهٔ پژوهشی تداش می‌تواند داده را به شکل زیر بخواند:

~~~python
from runtimes.tadash_body.social_observations import load_social_observations
data = load_social_observations("/path/to/private/public_social_snapshot.json")
assert not data["may_modify_body"]
assert not data["may_publish"]
# فقط آیتم‌های عمومی و نامطمئن برای بررسی پژوهشی
~~~

این مسیر یک رابط داده‌ایِ جداشده است، نه حلقهٔ خودکار یادگیری یا کنترل بدن. برای ادعای اتصال دائمی عملیاتی، چهار شاهد لازم است: Task/Timer فعال، snapshot تازه، نتیجهٔ موفق آخرین اجرای زمان‌بندی‌شده، و تداوم پس از خروج از RDP یا راه‌اندازی مجدد.

CI آزمون‌های آفلاین دارد و هیچ کلید واقعی در GitHub قرار داده نمی‌شود. آزمون آفلاین به‌تنهایی اتصال زنده را اثبات نمی‌کند.
