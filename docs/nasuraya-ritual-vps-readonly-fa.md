# راه‌اندازی آزمایشی Ritual Engine روی VPS لینوکسی

**وضعیت:** این طرح و کدهای آن هنوز روی سرور کاربر نصب نشده‌اند. هیچ پورت عمومی یا اتصال SSH در این چت ایجاد نشده است. راهنما برای Ubuntu 24.04، Python 3.12، کاربر غیر root و systemd نوشته شده است.

## معماری

| جزء | وظیفه |
|---|---|
| Ritual/NVLE | سه تمرین مصنوعی روزانه و حافظهٔ SQLite |
| BodyLoop از شاخه PR #140 | تولید وضعیت بومی شبیه‌ساز؛ بر بستر PR #136 |
| Bridge | فقط مشاهدهٔ `unified-status` روی کپی SQLite از BodyLoop |
| Timer daily | ساعت 08:00 UTC هر روز؛ ۳ تمرین محدود و replay-safe |
| Timer observer | هر ۱۵ دقیقه؛ ثبت snapshot وضعیت در دفتر جداگانه |

**مرز ایمنی:** Bridge هیچ فراخوانی `unified-step`، `step`، `api` یا actuator انجام نمی‌دهد. گزارش Native هرگز به عنوان پاداش واقعی در Ritual Engine تزریق نمی‌شود. در صورت ناهماهنگی رسیدها یا وضعیت نامعتبر، گزارش رد می‌شود. SHA-256 احراز هویت در برابر مهاجم نیست.

## نصب

از ایرانیکارت یک VPS **لینوکس Ubuntu 24.04** با SSH دریافت کن. ویندوز Server برای این راهنمای مستقیم مناسب نیست، زیرا BodyLoop از `fcntl` مخصوص لینوکس استفاده می‌کند. لطفاً IP و رمز ورود و کلید API را در گفت‌وگو منتشر نکن.

به عنوان کاربر غیر root در ترمینال Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y git python3
mkdir -p "$HOME/nasuraya"
git clone --depth=1 --single-branch --branch feature/nasuraya-ritual-vps-readonly-bridge-20261106 https://github.com/zurvanproject/zohraya.git "$HOME/nasuraya/ritual"
bash "$HOME/nasuraya/ritual/deploy/install_nasuraya_ubuntu.sh"
```

برای ادامهٔ اجرای systemd user پس از خروج از SSH، یک مدیر سیستم این دستور را اجرا کند:

```bash
sudo loginctl enable-linger "$(id -un)"
```

اسکریپت نصب هیچ کدی را به‌طور خودکار به نسخهٔ جدید تغییر نمی‌دهد و commit هر دو checkout را چاپ می‌کند.

در اولین نصب، تست‌های Ritual و BodyLoop اجرا می‌شوند، یک نشست **صفرکنش** برای BodyLoop ساخته می‌شود (mode bounded، حداکثر کنش صفر)، سپس `unified-enable` فراخوانی می‌شود. Ritual تمرین روز را در SQLite ثبت می‌کند، Bridge وضعیت را از snapshot می‌خواند و دو زمان‌بند فعال می‌شوند. هیچ step بومی انجام نمی‌شود.

## کنترل وضعیت

```bash
systemctl --user list-timers --all 'nasuraya-ritual-*'
systemctl --user status nasuraya-ritual-daily.timer nasuraya-ritual-observer.timer
journalctl --user -u nasuraya-ritual-observer.service -n 30 --no-pager
journalctl --user -u nasuraya-ritual-daily.service -n 30 --no-pager
```

توقف بدون حذف دیتابیس‌ها:

```bash
systemctl --user disable --now nasuraya-ritual-daily.timer nasuraya-ritual-observer.timer
```

برای اجرای مشاهدهٔ دستی، بدون حرکت:

```bash
cd "$HOME/nasuraya/ritual"
python3 -m unittest discover -s examples/nasuraya_virtual_learning/tests -v
python3 -m examples.nasuraya_virtual_learning.bridge \
  --ritual-db "$HOME/nasuraya/state/ritual.sqlite" \
  --bridge-db "$HOME/nasuraya/state/native-observer.sqlite" \
  --body-root "$HOME/nasuraya/body" \
  --body-session "$HOME/nasuraya/state/body.sqlite"
```

## گام بعدی

این نسخه «اتصال مشاهده‌ای زمان‌بندی‌شده» است و نه آموزش آنلاین BodyLoop. هرگونه اتصال یادگیری/کنش منوط است به: کالیبراسیون مدل فیزیکی ۷۸ کیلوگرمی، ثبت منشأ معتبر نتایج Native با شناسهٔ یکتا، حفظ veto حفاظت، آزمون‌های A/B و تأیید انسانی. PRها تا آن زمان در حالت Draft می‌مانند.
