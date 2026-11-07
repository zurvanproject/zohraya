# اتصال زندهٔ مدل زبانی به تداش — نتیجهٔ نهایی

۷ نوامبر ۲۰۲۶ (۱۶ آبان ۱۴۰۵)، PR #156 روی PR #155.

نشست واقعی Agents API با مدل `gpt-6-astra` و environment=none، وضعیت نرم‌افزار بدن را دریافت کرد، سه درخواست observe داد و پس از دریافت رسیدهای بومی، evaluate_goal را فراخواند. دور نهایی با وضعیت completed پایان یافت. ارزیابی مستقل سرور goal=3/3، revision=5 و پیشوند checkpoint برابر `037cccf654aa6f54` را تأیید کرد.

سه چرخهٔ تازه به دو چرخهٔ قبلی افزوده شدند؛ دو چرخهٔ قبلی به‌عنوان انجام این هدف شمارش نشدند. هر ابزار در فرایند تازهٔ VPS اجرا شد و همان goal و حافظه را ادامه داد. با فشار خواب شبیه‌سازی‌شدهٔ حدود ۰٫۹۵، مدل در هر سه نوبت observe را برگزید. این یک دور واقعیِ مدل به بدن نرم‌افزاری است؛ بهبود عمومی، تجربهٔ زیستی یا خودآگاهی از آن استنتاج نمی‌شود.

## شواهد سرور

| ابزار | درخواست | پاسخ | نتیجه |
|---|---|---|---|
| observe_body | [6706899988](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6706899988) | [6706908167](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6706908167) | `G=ACTIVE;N=0/3;R=2;E=0.999;F=0.011;P=0.115;S=0.950;Q=none;D=none;A=none;MEM=0;X=0;SIG=e56bddf4b641ec18;PHY=0` |
| request_body_action / observe | [6706949315](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6706949315) | [6706951450](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6706951450) | `G=ACTIVE;N=1/3;R=3;E=0.999;F=0.011;P=0.115;S=0.950;Q=observe;D=observe;A=observe;MEM=2;X=0;SIG=ca5c27d7106de3f9;PHY=0` |
| request_body_action / observe | [6706964580](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6706964580) | [6706972791](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6706972791) | `G=ACTIVE;N=2/3;R=4;E=0.999;F=0.011;P=0.115;S=0.950;Q=observe;D=observe;A=observe;MEM=2;X=0;SIG=9e39fa713176be9f;PHY=0` |
| request_body_action / observe | [6706984990](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6706984990) | [6706995616](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6706995616) | `G=DONE;N=3/3;R=5;E=0.999;F=0.011;P=0.115;S=0.950;Q=observe;D=observe;A=observe;MEM=2;X=0;SIG=037cccf654aa6f54;PHY=0` |
| evaluate_goal | [6707010138](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6707010138) | [6707018674](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6707018674) | `G=DONE;N=3/3;R=5;E=0.999;F=0.011;P=0.115;S=0.950;Q=none;D=none;A=none;MEM=0;X=0;SIG=037cccf654aa6f54;PHY=0` |

## اتصال به API و حریم

- SHA256 نشست: `b323508ac63d5456355cb1e144ebe301034f2208694700337db0a75428e8cda0`.
- SHA256 دور نهایی: `e3b7df74a778b64664e3dd48e18a3f06a6cd6f69fa6a857e50038e1aeea267f1`.
- چهار نتیجهٔ ابزار در دور نهایی تأیید ارسال شدند: سه عمل و یک ارزیابی.
- مشاهدهٔ اولیه پس از پایان نوبت نخست به‌عنوان شاهد تأییدشده در پیام ادامهٔ همان session/goal ارائه شد.
- متن گزارش، usage و شناسه‌های خام API در checkpoint خصوصی نگهداری شدند؛ در این مخزن نیستند.
- کلید تازهٔ اختصاصی با تأیید کاربر ساخته و فقط در مقصد محلیِ تأییدشده با مجوز 0600 ذخیره شد. مقدار آن در خروجی عادی، GitHub، سرور، checkpoint گزارش یا sandbox قرار نگرفت.
- پس از نگهداری گزارش، session آزمایشی API حذف شد. environment=none بود؛ sandbox ساخته نشد. کلید لغو نشد و دفتر تداش حفظ شد.

## منشأ بایت‌های اجراشده

- پاسخ 6706908167: commit `7e33a82285f9cfbc7d1b3240af0d91cbf467c09a`؛ SHA256 فایل `8b57de5b4ee2892a6cac345d34d16860f12330727dc5355f3ab3bf832f1571d5`؛ call identity هش‌شده `05ab680ce33248e3d9fa84da561c514f350f3320b1c0cdea3d30cdf410be0cb8`.
- پاسخ 6706951450: commit `94887f812e8bfd45b48a05f335f8b1a820e2e3d8`؛ SHA256 فایل `93cd55a8d168e64e900a56ff0e0b15f5998255792fdc0bf672082039cbd3f302`؛ call identity هش‌شده `f04bdc3856caf078c5251670a8007fbe5fbcbf0fc3e91dbfded46f4f835bc568`.
- پاسخ 6706972791: commit `e17700944ccff39d063bbadac6b366016973e883`؛ SHA256 فایل `083555326d89985f4ce27e4d543b8c62dd20f6447cdff1e9956caa5e0f7afb4d`؛ call identity هش‌شده `3a3edcf624031550d1b55babeccf049bf1906d82f1e35b6b5583542f2f7ce50b`.
- پاسخ 6706995616: commit `029fdfcf70bd82de45f9feb2f02077071fffb6b1`؛ SHA256 فایل `b570bab405944536fda1b2af58587c0d325bd406ac17eab54fa5455bbc44f54d`؛ call identity هش‌شده `3635357d7718824edd97c3659b86939dba14a965d7e000f23f96ea85bc5451e9`.
- پاسخ 6707018674: commit `ca5e7303b0ec6d40baabd79d983dc402ccf025e7`؛ SHA256 فایل `05490695092dc190ec0fb5c71f8b89a3395fdcb37ee7f69f515f2885ecc9b46f`؛ call identity هش‌شده `b9ea8652f19b895177207a51c1e68851242158014894675f4965d3429b4e3166`.

کد نهاییِ آزموده‌شده در `ca5e7303b0ec6d40baabd79d983dc402ccf025e7` قرار دارد. منبع هر job قبل از صف‌شدن با نسخهٔ محلی تطبیق کامل داشت. ۷۰ فایل اصلی native از PR #155 تغییر نکردند. مقادیر عمومی به سه رقم اعشار گرد شده‌اند و SIG صرفاً پیشوند SHA256 است، نه امضای سخت‌افزاری.

## موارد اصلاح‌شده در اجرای واقعی

۱. API حساب گزینهٔ اختیاری spend_control را با HTTP 400 / unknown_parameter نپذیرفت. از قرارداد پایهٔ مستند استفاده شد؛ سقف دلاری سرویس ادعا نمی‌شود. سقف سه چرخه و ۱۲ ابزار در میزبان باقی است.

۲. [درخواست فقط‌خواندنی نخست](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6706881390) با [UnicodeDecodeError](https://github.com/zurvanproject/zohraya/issues/149#issuecomment-6706886013) رد شد. پل Python -I را بدون UTF-8 صریح آغاز می‌کند؛ ورودی Windows با -X utf8 بازاجرا و تست‌ها با ورودی واقعی اصلاح شدند. این درخواست شکست‌خورده چرخه‌ای اضافه نکرد؛ مشاهدهٔ موفق بعدی همان revision=2 و checkpoint قبلی را داشت.

۳. هنگام آماده‌سازی backend، turn نخست منتظر ابزار ماند و بدون چرخهٔ بدنی تمام شد. نتیجهٔ دیررس به‌عنوان tool result موفق جعل نشد. همان session و قرارداد هدف، با شاهد مشاهدهٔ واقعی در turn بعدی ادامه یافت. هدف و بودجه reset نشدند.

۴. نبود pending به‌تنهایی شاهد تحویل نتیجهٔ API نیست؛ تحویل نامعلوم برای تطبیق صریح متوقف می‌شود. بدن دوباره اجرا نمی‌شود.

## آزمون

[workflow نهایی](https://github.com/zurvanproject/zohraya/actions/runs/42373119231): ۱۸ آزمون در Windows و ۱۸ آزمون در Linux، همه موفق. jobهای 128405135937 و 128405136182.

آزمون‌ها هدف/session پایدار، سه چرخه در فرایندهای جدا، سقف پایدار، replay، payload متعارض، نبود مشاهده، قطع بین commit بدن و ثبت goal، دفتر بیگانه، تحویل نامعلوم، ادامهٔ turn تکمیل‌شده و رد پاسخ با نویسنده/شناسه/دامنهٔ نامعتبر را پوشش می‌دهند.

[workflow میزبان قبلی](https://github.com/zurvanproject/zohraya/actions/runs/42373119147) نیز برای همان منبع موفق شد.

## محدودهٔ اثر

این مسیر caller-mediated است: گردانندهٔ Work درخواست مدل را به پل و رسید را به مدل برمی‌گرداند. listener همیشگی روی VPS، انتقال کلید به سرور، اتصال خودکار همهٔ پیام‌های ChatGPT و recovery پس از reboot برقرار نشده‌اند.

مدل native، شبیه‌ساز تجمیعی قدیمیِ ۱۹۵ کیلوگرمی است؛ مدل مفصلی ۷۸ کیلوگرمی و forecaster مربوط به PR #154 جدا هستند. هیچ actuator فیزیکی، reset دفتر قبلی، merge به main یا تغییر وزن ChatGPT انجام نشد.

معیار پذیرش اصلی برآورده شد: هدف مشخص و سقف سه چرخه، مشاهده و تصمیم مدل و اجرای بومی، حفظ goal و سابقه در فرایند تازه، و تأیید تکمیل هم از دفتر سرور و هم از terminal turn API.

