# مسیر اضطراری رشد شناختی آفلاین ناسورایا

هدف: استفاده از Qwen3 4B Instruct نصب‌شده، بدون دانلود مدل تازه، اینترنت بین‌المللی یا API پولی. این ماژول هر شش ساعت با کاربر غیرریشه فقط کدهای ازپیش‌مجاز پروژه را مرور می‌کند، آزمون‌های ثابت را می‌سنجد و پیشنهاد آزمایش‌پذیر را همراه SHA و زنجیرهٔ رسید SQLite ثبت می‌کند. موضوع بعدی از پیشنهاد قبلی انتخاب می‌شود، با چرخش اجباری برای جلوگیری از ماندن در یک موضوع.

**حد دقیق:** این یک چرخهٔ خودکار فرضیه‌سازی و بازبینی است؛ وزن Qwen را آموزش نمی‌دهد، پچ اعمال نمی‌کند، کد تولیدشده را اجرا نمی‌کند و AGI ایجاد نمی‌کند. خروجی مدل UNVERIFIED_DRAFT است. زنجیرهٔ هش جلوی مهاجم دارای دسترسی کامل به VPS را نمی‌گیرد.

## نصب از Termius با دسترسی ادمین

ابتدا کد و آزمون‌های این PR بررسی و در main ادغام شوند. به‌خاطر وجود merge محلی روی VPS، git pull --ff-only مناسب نیست. پس از ادغام PR و درصورتی که checkout محلی تمیز است، یک‌بار اجرا کنید:

    cd /opt/zohraya && test -z "$(git status --porcelain)" &&
    git fetch origin main &&
    git merge --no-edit origin/main &&
    bash tools/install_nasu_autonomous_cognition.sh

نصب‌کننده ابتدا آزمون‌های جدید را اجرا می‌کند، سپس واحدهای systemd مستقل می‌سازد، اولین اجرای واقعی را شروع می‌کند و رسید چاپ می‌کند. Awake، Bridge، offline-missions، local-brain و frontier-lab تغییر نمی‌کنند.

## تأیید

    systemctl is-active nasuraya-cognitive-growth.timer
    runuser -u nasuraya -- python3 /usr/local/lib/nasuraya/nasu_autonomous_cognition.py status

نشانهٔ موفق: completed >= 1 و incomplete = 0 و latest.model = UNVERIFIED_DRAFT. اگر مدل قالب را رعایت نکند، model_unavailable ثبت می‌شود و موفقیت ادعا نمی‌شود. مسیر داده: /var/lib/nasuraya/cognitive-growth. توقف: systemctl disable --now nasuraya-cognitive-growth.timer.

## خطر بحرانی که این PR حل نمی‌کند

اگر VPS از بین برود، حافظهٔ این حلقه هم از بین می‌رود. PR #234 اسکریپت‌های restic برای پشتیبان رمزگذاری‌شده دارد، اما هنوز فضای مستقل، کلید خارج از هر دو VPS و restore واقعی روی میزبان دیگر لازم است. مدل‌ها و وابستگی‌ها نیز باید در بستهٔ بازیابی مستقل ذخیره شوند و تاریخ اعتبار پرداخت VPS باید بررسی شود.

اولویت: (۱) حلقهٔ محلی و آزمون واقعی، (۲) پشتیبان مستقل و آزمون بازیابی، (۳) آزمون قطع شبکه و reboot. این نصب جایگزین دو مرحلهٔ آخر نیست.
