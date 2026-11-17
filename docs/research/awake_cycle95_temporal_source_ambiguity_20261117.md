# Tadash Awake | Cycle 95: temporal source ambiguity audit

**Date:** 2026-11-17
**Scope:** synthetic, reproducible, non-operational research only
**Repository:** https://github.com/zurvanproject/zohraya
**Original pinned head of PR #205:** \`90692bde9f1e4b5b7f311162b7c83127715df710\`
**Research patch:** https://github.com/zurvanproject/zohraya/pull/259 (draft, unmerged)
**Test patch commit:** \`2813d78ebb1c6350141e1b1dd50c7f1ee7f39dfb\`
**Original finding:** https://github.com/zurvanproject/zohraya/pull/205#issuecomment-6947605919

## مسئله و نتیجه

در نسخهٔ پین‌شده، تابع \`tadash_awake.core.propose()\` برای وقوع \`temporal_change\` فقط تفاوت مقادیر، سازگاری ساعت‌ها و فاصلهٔ زمانی بیش از پنجره را بررسی می‌کند. شرط تغییر زمانی، وجود دو مشاهدهٔ متفاوت **از یک منبع یکسان** را الزام نمی‌کند. در نتیجه دو مقدار متفاوت از دو منبع A/B در زمان‌های متفاوت می‌توانند همان نتیجهٔ تغییر در منبع A در طول زمان را بدهند.

این یک **ابهام انتساب منشأ شواهد** است، نه اثبات نادرست‌بودن سنسورها یا عدم تغییر واقعی پدیده. Awake فعلاً پرسش پژوهشی می‌سازد. در این ممیزی هیچ شاهد حسی واقعی، دادهٔ بیمار یا وضعیت VPS بررسی یا جابه‌جا نشده است.

## روش بازتولید مستقیم

Fixtures مصنوعی با \`source_ref\`های \`tadash://fixture/a\` و \`tadash://fixture/b\` و موضوع \`time_topic\` ابتدا از \`core.checked()\` گذشته و سپس **خود تابع واقعی** \`core.propose()\` فراخوانی شده است (نه کپی محدود منطق). آزمون‌ها در \`tadash_awake/test_wake.py\` و اصلاح در \`tadash_awake/core.py\`، در شاخهٔ PR #259 ثبت شده‌اند.

\`\`\`bash
python -m unittest tadash_awake.test_wake tadash_awake.test_bridge -v
\`\`\`

برای اجرای baseline، از commit پین‌شدهٔ \`90692bde9f1e4b5b7f311162b7c83127715df710\` استفاده کنید؛ نسخهٔ آزمایشی پیش از اصلاح در اجرای CI شمارهٔ 44092459464 ثبت شده است:
https://github.com/zurvanproject/zohraya/actions/runs/44092459464

### خروجی واقعی baseline (synthetic)

| Fixture | \`kind\` | \`rank\` |
|---|---|---:|
| A@1 sec = 0, A@2 sec = 1 | \`temporal_change\` | 4 |
| A@1 sec = 0, B@2 sec = 1 | \`temporal_change\` | 4 |
| A@1 sec = 0, B@1.05 sec = 1 | \`discrepancy\` | 5 |
| Mixed \`sample_time\` and UTC domain, differing values | \`time_scope_uncertain\` | 5 |
| A at T = 0 min, A at T + 15 min, 0 to 1 | \`temporal_change\` | 4 |
| A at T = 0 min, B at T + 15 min, 0 to 1 | \`temporal_change\` | 4 |
| A@1 = 0, A@1.5 = 0, B@2 = 1 | \`temporal_change\` | 4 |
| A@1 = 0, B@1.05 = 0 | \`falsification\` | 1 |
| A@1 = 0, A@1 = 1 | \`independent_check\` | 3 |

**Baseline CI:** Ubuntu 22/22 tests passed; Windows 22/22 tests passed. The observations above are printed by the suite with \`AWAKE_SYNTHETIC_BASELINE\` markers.

### Invalid and incompatible time tests

The input validator \`core.checked()\` rejects \`sample_time\` values that are NaN, infinity, negative, strings, bool or greater than 1,000,000. It also rejects unparseable or timezone-naive \`observed_at\`. Differing values with inconsistent presence of \`sample_time\` are classified as \`time_scope_uncertain\` (rank 5).

Directly calling \`propose()\` on unvalidated raw records is outside the tested ingestion contract; this audit **does not** claim \`propose()\` itself validates malformed samples.

## اصلاح حداقلی، فقط برای تفسیر

در صورت \`kind == "temporal_change"\` و حضور چند منبع، بررسی می‌شود آیا **درون حداقل یک منبع واحد** جفتی از نمونه‌های دارای مقدار متفاوت و فاصلهٔ زمانی بیشتر از پنجرهٔ موجود وجود دارد یا نه.

اگر چنین جفتی وجود نداشت، تنها فیلد اختیاری زیر به دیکشنری خروجی **مستقیم** \`propose()\` افزوده می‌شود:

\`\`\`python
"interpretation": "cross_source_temporal_ambiguity"
\`\`\`

- \`kind\`، \`rank\`، متن سؤال، \`hash\`، \`latest\`، \`evidence_count\` و تقدم \`discrepancy\` تغییر نمی‌کنند.
- \`tick()\`، \`status()\`، \`checked()\`، \`ingest()\`، شِمای SQLite، ثبت پرسش، Bridge و scheduling تغییری نکرده‌اند.
- \`interpretation\` فعلاً به \`tick()\` یا ذخیره‌سازی منتقل نمی‌شود، و برای تصمیم عملیاتی معتبر نیست.
- بررسی تغییر درون یک منبع با پیمایش خطی و استفاده از کمینه/بیشینهٔ زمان نمونه‌برداری انجام می‌شود، به‌جای مقایسهٔ تمام زوج‌ها. علت‌سنجی نهایی همچنان نیازمند کالیبراسیون، تکرار آزمایش و سنجش نویز است.

### خروجی واقعی اصلاح و کنترل رگرسیون

| Fixture | \`kind/rank\` (unchanged) | Optional \`interpretation\` |
|---|---|---|
| Same-source sequential change A→A | \`temporal_change / 4\` | absent |
| Different sources at different times A→B | \`temporal_change / 4\` | \`cross_source_temporal_ambiguity\` |
| A unchanged in repeated samples, B different later | \`temporal_change / 4\` | \`cross_source_temporal_ambiguity\` |
| Simultaneous contradiction A/B | \`discrepancy / 5\` | absent |
| Mixed clock domains | \`time_scope_uncertain / 5\` | absent |
| Same-source middle change, equal endpoint values | \`temporal_change / 4\` | absent |
| 500 stable A samples + one later differing B | \`temporal_change / 4\` | \`cross_source_temporal_ambiguity\` |

**Final verified CI:** https://github.com/zurvanproject/zohraya/actions/runs/44093660928
**Ubuntu: 26 tests passed. Windows: 26 tests passed.**

A prior test run initially failed due to a missing isolated SQLite temp directory in the new test class, not the production code; it was fixed, rerun successfully and recorded in the draft PR history.

## محدودهٔ اعتبار

- داده‌ها همگی مصنوعی و ایزوله‌اند.
- برچسب \`cross_source_temporal_ambiguity\` فقط عدم کفایت شواهد **درون‌منبعی** برای ادعای روند زمانی را یادآوری می‌کند، نه اینکه تغییر فیزیکی واقعی ناممکن بوده باشد.
- صحت کالیبراسیون، بار نویز، هم‌زمان‌سازی مستقل ساعت‌ها و رفتار سنسور واقعی با این آزمون‌ها اثبات نشده‌اند.
- تغییر دادن خروجی عملیاتی \`tick()\`، رتبه‌ها یا persistence به طراحی، تست و تأیید جداگانه نیاز دارد.

## وضعیت، روش بازگشت و دروازهٔ تأیید

**وضعیت ثبت:** این فایل و آزمون‌ها فقط در شاخهٔ \`research/awake-temporal-source-ambiguity-20261117\`، از طریق PR #259 (Draft) نگهداری می‌شوند؛ ادغام در شاخهٔ PR #205 یا \`main\` انجام نشده و هیچ انتقالی به VPS انجام نشده است.

**قبل از ادغام:** بستن PR #259 بدون merge برای بازگشت کافی است؛ شاخهٔ PR #205 و \`main\` دست‌نخورده‌اند.

**در صورت ادغام مجاز در آینده:** commit ادغام/squash روی شاخهٔ مقصد revert شود و همان آزمون‌ها دوباره اجرا شوند؛ شِمای SQLite migration ندارد. اگر استقراری بعداً با مجوز انجام شود، پیش از جابه‌جایی نسخه Awake را pause کنید و پس از بازگردانی، سلامت وضعیت را بررسی کنید. حافظه و DB نباید بی‌اجازه پاک شوند.

**Approval required:** هر ادغام، انتقال به VPS، یا تغییر رفتار عملیاتی Awake به اجازهٔ صریح و جداگانهٔ صاحب پروژه نیاز دارد.

**Tracking:** https://github.com/zurvanproject/zohraya/pull/205#issuecomment-6949458282
