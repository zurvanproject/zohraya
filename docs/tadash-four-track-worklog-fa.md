# دفتر ادامهٔ چهار مسیر تداش

تاریخ آغاز: ۲۰۲۶/۱۱/۰۲. شاخهٔ مجاز: `nasuraya/four-track-lab-20261102`.
مبنای ثابت: PR #110، commit `77acf7f687a6b6e93804c1c8230fdafccd112b2d`.
این کار دستور صریح سهند برای پیشبرد مرحله‌های کم‌خطر بدون درخواست تأیید دوباره است، نه مجوز هزینه، استقرار، ادغام یا تغییر state زنده.

## حدود
فقط کد جدید آزمایشی و PR پیش‌نویس. main، مدل بدن، حافظهٔ مرجع، اسرار و مجوزها تغییر نمی‌کنند. API پولی، GPU اجاره‌ای، actuator فیزیکی، دانلود وزن بزرگ، مدل خودویرایشگر و سرویس دائمی اجرا نمی‌شوند. کار زمان‌بندی‌شده سه نوبت ساعتی دارد و نباید تمدید شود. بازگشت/توقف کاربر، در صورت مشاهده، به معنای عدم آغاز کار تازه است.

## مرحلهٔ اول ساخته‌شده
۱. **PhyAgentOS-inspired outcome review:** مقایسهٔ جفتی `slow_breath` با `observe`، نتیجهٔ `met/not_met/inconclusive`، حفظ وتوی بدن، بررسی پنج شاخص نرم‌افزاری. آستانه‌های ۰٫۰۰۵ و ۰٫۰۱ انتخاب پژوهشی ما هستند؛ نه حدود بالینی و نه پارامترهای upstream. کتابخانهٔ PhyAgentOS نصب نشده است.
۲. **Hindsight export:** سه سند جداگانهٔ نیت، مشاهده و برداشت؛ metadata برچسب ماست و معادل fact_type استنباطی Hindsight نیست. شناسهٔ سند به هش رسید وابسته است. `timestamp=unset` مانع جا زدن زمان شبیه‌سازی به‌جای زمان واقعی می‌شود. داده فقط مصنوعی است. هیچ retain/recall server اجرا نشده؛ شواهد خام جداگانه حفظ می‌شوند.
۳. **mjlab preflight:** موجودی XML و حسابرسی ساختاری، بدون ادعای compilation. جرم حرارتی literal=195 در منبع از جرم گزارش‌شدهٔ اطلس=78 در PR100 جداست. این دو هنوز یک مدل یکپارچه نیستند. فقدان XML روی این مبنا blocked است، نه موفقیت. از مدل اسباب‌بازی به‌جای اطلس اختصاصی استفاده نشده است.
۴. **Dream Rehearsal preparation:** پیش‌بینی frozen پیش از عمل، کنترل persistence و منع نشت شناسه‌های train/eval. نامزد فعلی فقط میانگین تغییر به تفکیک فرمان است، نه DreamerV3 یا کد upstream. حتی برتری این pilot اجازهٔ imagined replay یا آموزش actor نمی‌دهد؛ دادهٔ مستقل آینده و ارزیابی چندمرحله‌ای لازم است.

## آزمایش ازپیش‌تعیین‌شده
دو زمینهٔ مصنوعی baseline و post_walk، سه افق ۰٫۱، ۰٫۵ و ۱ ثانیه، دو بازوی کنترل و تنفس آهسته: ۱۲ مسیر / ۶ مقایسه / ۶۴ چرخهٔ مداخله، افزون بر initialization. هر بازو از بدن مستقل با checkpoint اولیهٔ کامل برابر آغاز می‌شود. ۳۲ گذار baseline برای مدل delta و ۳۲ گذار post_walk برای ارزیابی؛ افق‌ها prefix مشترک دارند و نمونهٔ آماری مستقل نیستند. پس از baseline، مدل freeze می‌شود؛ پیش‌بینی هر رویداد پیش از عمل با fsync ذخیره می‌شود. شش مقایسهٔ outcome پژوهشی‌اند، نه کارآزمایی درمانی.

خروجی در مسیر تازه با mkdir انحصاری ساخته می‌شود؛ استفادهٔ دوباره از همان مسیر رد می‌شود. قطع اجرا `failed_or_unknown` می‌شود و نباید بی‌بررسی تکرار شود. این قفل محلی است، نه قفل توزیع‌شده. کپی runtime موقت است؛ کد trusted پروژه اجرا می‌شود، نه sandbox عمومی برای کد متخاصم. محیط فرزند credential ندارد و برنامه هیچ client شبکه‌ای ندارد.

## شواهد ثبت‌شده تا پیش از اولین CI
۲۲ آزمون واحد محلی موفق شدند. syntax compilation موفق بود. بررسی مقدماتی محلی به‌درستی `blocked: complete_native_checkout_missing` داد، زیرا محیط فعلی DNS مستقیم GitHub ندارد. این نتیجه اجرای native نیست. اجرای native باید از لاگ workflow اختصاصی و artifact بررسی شود. صرف ایجاد PR یا سبز بودن workflow دیگر، اثبات این آزمایش نیست.

## فرمان‌ها
```bash
python -m unittest -v experiments.tadash_four_tracks.test_core
python -m experiments.tadash_four_tracks.run_probe --output /tmp/tadash-four-track-unique-run
```
Workflow: `.github/workflows/tadash-four-tracks.yml`. Python 3.12، stdlib-only، بدون نصب وابستگی یا درخواست مدل. artifact هفت روز نگه داشته می‌شود؛ شواهد مهم را به خلاصهٔ کوچک دائمی با شناسهٔ اجرا منتقل کنید، نه state شخصی.

## منابع بررسی‌شده و مرز استفاده
- https://github.com/PhyAgentOS/PhyAgentOS-core/tree/v1.1.1 : تفکیک execution و verification؛ فقط الهام معماری، هیچ کد upstream کپی نشده.
- https://github.com/vectorize-io/hindsight/blob/v1.1.0/hindsight-docs/docs/developer/api/retain.mdx : fields content/context/timestamp/document_id/metadata. سرویس استخراج اطلاعات از مدل زبانی استفاده می‌کند؛ بدون مدل محلی معتبر فعال نشود.
- https://mujocolab.github.io/mjlab/v1.6.0/source/installation.html : آموزش نیازمند NVIDIA GPU است. هنوز mjlab وارد runtime نشده.
- https://github.com/gurpnijjer/dream-rehearsal : استفادهٔ مفهومی؛ commit و مجوز هنوز برای واردکردن کد تثبیت نشده‌اند، بنابراین اجرای upstream مجاز نیست.
- https://github.com/zurvanproject/zohraya/pull/100 : توصیف مدل‌های جداگانه و نتیجهٔ قبلی RSSM؛ اعداد قبلی جای نتیجهٔ آزمایش تازه نیستند.
- https://github.com/zurvanproject/zohraya/blob/refs/pull/95/head/examples/nasuraya_research/articulated/motion_commands.py : نقطهٔ شروع خواندن codebase حرکت؛ پیش از اجرای آن head SHA و dependencies بررسی شود.

## دستور ادامه برای نوبت‌های زمان‌بندی‌شده
ابتدا وضعیت PR همین شاخه و workflow را بخوان. اگر در حال اجراست تکرار نکن. لاگ tests و native را جداگانه ببین. اگر شکست، همان خطای مشخص را اصلاح و آزمون regression اضافه کن؛ نتیجهٔ منفی فیزیولوژیک را با تغییر threshold سبز نکن. نتیجهٔ مرور را زیر همین دفتر اضافه کن.

سپس به‌ترتیب: بازسازی مستقل امتیازها و صحت export؛ بررسی timing/identity قراردادها؛ تثبیت SHA و بررسی مجوز چهار منبع پیش از هر import؛ بازیابی کد واقعی اطلس از PR95 و compilation محدود CPU در workspace جدا، بدون ادغام PR95؛ schema validation واقعی Hindsight با dependency سبک فقط در محیط آزمایشی، بدون راه‌اندازی مدل/سرویس پولی؛ ارزیابی چندگامی مستقل فقط پس از ثبت پروتکل جدید، بدون actor training یا تغییر وزن ChatGPT. اگر مسیر به GPU، credential یا هزینه رسید، blocked با علت ثبت کن و به مسیر دیگر برو. ادامه بدون سؤال به معنی عبور از این مرزها نیست.
