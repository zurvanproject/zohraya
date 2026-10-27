"""Render the retained experiment; never run physics or choose a new policy."""
import argparse
import base64
import gzip
import html
import json
import math
from pathlib import Path


def render(folder,doc):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    folder=Path(folder);doc=Path(doc)
    decision=json.loads((folder/'promotion-decision.json').read_text())
    plan=json.loads((folder/'protocol.json').read_text())
    audit=json.loads((folder/'integrity-audit.json').read_text())
    def row(case,variant):return json.loads((folder/(case+'--'+variant+'.json')).read_text())
    def result(case,variant):return row(case,variant)['result']
    names={'fresh_low_negative':'اصطکاک ۰٫۳۸، هل −۹ N',
           'fresh_high_positive':'اصطکاک ۰٫۷۲، هل +۱۱ N',
           'fresh_long_negative':'قدم ۷ cm، هل −۷ N',
           'fresh_half_dt':'گام زمانی ۰٫۵ ms، هل +۶ N',
           'fresh_six_low':'شش قدم، اصطکاک ۰٫۴۶',
           'fresh_six_negative':'شش قدم، هل −۱۰ N'}
    def table(headers,rows):
        return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+
                         ['| '+' | '.join(str(x) for x in r)+' |' for r in rows])
    rms=[];speeds=[]
    for case in plan['holdouts']:
        b,p,c=[result(case['id'],v) for v in ('baseline','prior6','combined6')]
        rms.append([names[case['id']],f"{b['tilt_rms_deg']:.6f}",f"{p['tilt_rms_deg']:.6f}",f"{c['tilt_rms_deg']:.6f}",
                    f"{100*(c['tilt_rms_deg']/b['tilt_rms_deg']-1):+.2f}%",f"{100*(c['tilt_rms_deg']/p['tilt_rms_deg']-1):+.2f}%"])
        speeds.append([names[case['id']],case['steps'],f"{c['simulated_seconds']:.3f}",
                       f"{b['final_max_generalized_speed']:.6f}",f"{p['final_max_generalized_speed']:.6f}",f"{c['final_max_generalized_speed']:.6f}"])
    diagnostic=[]
    for v,title in [('baseline','پایه صفر'),('prior6','بایاس ثابت +۶ mm'),('landing6','فقط محو بایاس'),
                    ('tail6','فقط میرایی با +۶ mm'),('tail0','فقط میرایی با صفر'),('combined6','ترکیبی جدید')]:
        p=result('known_push',v);t=result('known_tail',v)
        diagnostic.append([title,f"{p['tilt_rms_deg']:.6f}",f"{t['tilt_rms_deg']:.6f}",f"{t['final_max_generalized_speed']:.6f}",
                           'رد توقف' if t['final_max_generalized_speed']>=.05 else 'قبول توقف'])
    fig,(ax,bx)=plt.subplots(1,2,figsize=(13,4.6),gridspec_kw={'width_ratios':[1.7,1]})
    colors=['#147d92','#b96b0d','#b53848']
    for v,label,color in zip(('baseline','prior6','combined6'),('Zero-offset baseline','Previous +6 mm','New combined controller'),colors):
        tr=json.loads(gzip.decompress((folder/('known_push--'+v+'-trace.json.gz')).read_bytes()))
        ax.plot([r['t'] for r in tr],[r['tilt_deg'] for r in tr],color=color,label=label,linewidth=1.65)
    for start,end,label in ((11,12,'Landing 2'),(12,15,'Recenter'),(15,17,'Settle')):
        ax.axvspan(start,end,alpha=.07,color='#173b57' if start!=12 else '#b96b0d')
        ax.text((start+end)/2,.97,label,transform=ax.get_xaxis_transform(),ha='center',va='top',fontsize=8)
    ax.set(xlabel='Measured motion time (s)',ylabel='Pelvis tilt (degrees)',title='Known +10 N lateral push: retained replay',xlim=(0,17))
    ax.grid(alpha=.18);ax.legend(fontsize=8,loc='upper left')
    variants=['baseline','prior6','tail0','combined6']
    values=[result('known_tail',v)['final_max_generalized_speed'] for v in variants]
    bx.bar(['Zero','Old +6','Tail only\nzero','New\ncombined'],values,color=['#147d92','#b96b0d','#786294','#b53848'])
    bx.axhline(.05,color='#b53848',linestyle='--',linewidth=1,label='Unchanged 0.05 limit')
    bx.set(ylabel='Absolute tail_yaw_1 speed (rad/s)',title='Known terminal failure: final limiting joint',ylim=(0,.083))
    for i,value in enumerate(values):bx.text(i,value+.0015,f'{value:.5f}',ha='center',fontsize=8)
    bx.legend(fontsize=8,loc='upper right');bx.grid(axis='y',alpha=.18)
    fig.tight_layout();fig.savefig(folder/'comparison.png',dpi=170);fig.savefig(folder/'comparison.svg');plt.close(fig)
    svg=folder/'comparison.svg'
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines())+'\n')
    text=f'''# آزمایش فرود نهایی و آرام‌شدن دم ناسورایا — ۲۷ اکتبر ۲۰۲۶

**نتیجه: نسخهٔ محدود پیاده و اندازه‌گیری شد؛ معیار عملکرد مستقل رد شد و ارتقا ممنوع است.**

۳۰ اجرای پروتکل، ۸۴ قدم پذیرفته‌شده و ۳۴ آزمون نرم‌افزاری موفق ثبت شد. هر ۳۰ اجرا قدم‌های خواسته‌شده را کامل کردند؛ دو اجرای تشخیصی شرط سرعت پایانی را رد کردند. ۱۸ اجرای مستقل تازه همگی قدم‌ها و توقف را گذراندند، اما دو شرط مقایسهٔ عملکرد رد شدند. دو اجرای اضافی Haswell، خارج از این ۳۰ اجرا، چهار قدم دیگر را کامل کردند؛ مجموع کار فیزیکی این نوبت ۳۲ اجرا و ۸۸ قدم است.

## تغییر محدود

در فرود آخر (برای حرکت دوقدمی، فرود دوم)، بایاس جلو/عقب با تابع نرم مرتبهٔ پنج، در همان یک ثانیهٔ موجود از +۶ میلی‌متر به صفر می‌رسد؛ در بازگشت به مرکز و توقف، صفر باقی می‌ماند. هم‌زمان یک وظیفهٔ نرم برای دم در همان حل‌گر مقید افزوده می‌شود: شتاب هدف `50 × خطای وضعیت خنثی − 20 × سرعت`، با وزن افزایشی صفر تا یک. وظیفهٔ عمومی قبلی `50 × خطا − 12 × سرعت` با وزن ۰٫۱ حفظ شده است. افزایش وزن و میرایی دو مؤلفهٔ همین مداخله‌اند؛ اثر جداگانهٔ آن‌ها تفکیک نشده است.

مدل، جرم ۷۸ کیلوگرمی، محدودهٔ گشتاور، قیدهای فشار و اصطکاک، دروازهٔ برداشتن پا، شرط پذیرش فرود، هل اعمال‌شده و زمان‌بندی عوض نشدند. هیچ وضعیت یا سرعتی مستقیماً بازنویسی نشد. تغییرها فقط در `landing_settle.py`، یک نسخهٔ آزمایشی جدا از دو روال عددی اصلی، قرار دارند؛ این جداسازی برای حفظ اتصال شواهد و checkpointهای منبع قبلی است. توابع هندسه و تماس از منبع قبلی وارد می‌شوند. ذخیره و بارگذاری checkpoint در مسیر آزمایشی صریحاً رد می‌شود.

## مشاهدات قطعی و علت‌های هنوز اثبات‌نشده

- چهار اجرای صفر و +۶ میلی‌متریِ دو مورد شناخته‌شده، هر ۲۸ فیلد مشترک و تمام رد زمانی قبلی را عیناً بازتولید کردند؛ اختلاف از محیط عددی این مقایسه نیست.
- در هل +۱۰ N، RMS فاز فرود دوم در نسخهٔ قبلی از ۰٫۱۵۱۲۸۲ به ۰٫۳۲۴۷۳۴ درجه، و فاز بازگشت از ۰٫۱۳۰۵۵۸ به ۰٫۴۴۶۹۶۵ رسید. این فازها محل افزایش خطا هستند؛ اندازه‌گیری زمانی به‌تنهایی علت کامل مکانیکی را تعیین نمی‌کند.
- در منبع، شروع فرود محدودیت تقسیم بار را از حالت انتقال وزن به `None` می‌برد و هر دو پا را پشتیبان برنامه‌ریزی‌شده حساب می‌کند؛ بایاس ثابت نیز تا پایان می‌ماند. برهم‌کنش تماس، تقسیم بار و اهداف QP علت‌های محتمل‌اند. این آزمایش سهم هرکدام را به‌طور کامل جدا نکرد.
- محو بایاس به‌تنهایی خطای کل هل را به ۰٫۲۶۱۳۹۷ رساند؛ پس فرضِ «باقی‌ماندن بایاس تنها علت مشکل است» از این مداخله پشتیبانی نمی‌شود. میرایی با بایاس صفر هم همان مورد هل را بدتر کرد. اثر دم از تعادل کل بدن مستقل نیست.
- در مورد توقف ناقص، مفصل محدودکننده واقعاً `tail_yaw_1` بود: −۰٫۰۶۶۵۱۷ rad/s. افزایش میرایی به‌تنهایی با بایاس صفر، آن را به −۰٫۰۶۷۲۲۶ رساند و مشکل را حل نکرد. نسخهٔ قبلیِ +۶ mm خودش توقف را به ۰٫۰۰۱۹۳۴ می‌رساند؛ نسخهٔ ترکیبی ۰٫۰۰۱۶۲۰ شد. نباید کل کاهش از پایهٔ صفر را به اصلاح تازه نسبت داد.
- ۱۴ مقایسهٔ رد زمانی نشان دادند حالت‌ها تا پیش از فرود آخر دقیقاً با کنترل متناظر برابرند؛ مداخله واقعاً محدود به پایان حرکت است.

## حذف مؤلفه‌ها روی دو شکست شناخته‌شده

این داده‌ها تشخیصی‌اند و اعتبارسنجی مستقل محسوب نمی‌شوند. همهٔ ردیف‌ها دو قدم معتبر در ۱۷ ثانیه دارند.

{table(['نسخه','RMS هل، درجه','RMS مورد دم، درجه','بیشینه سرعت نهایی در مورد دم، rad/s','نتیجهٔ توقف'],diagnostic)}

## شش شرایط تازه: مقایسهٔ RMS

پروتکل، منبع و هر شش شرایط قبل از اولین اجرا در commit محلی `12dd819` ثابت شدند. پس از دیدن نتیجه هیچ پارامتر یا سناریویی تعویض نشد. چهار حرکت دوقدمی، دو حرکت شش‌قدمی، دو علامت هل، چند اصطکاک و گام زمانی نصف بررسی شدند. «تازه و مستقل» یعنی وارد انتخاب تنظیم نشده‌اند؛ آن‌ها نمونه‌های زیستی یا آماری مستقل نیستند. انتشار بیرونی پیش از اجرا انجام نشده است.

عدد مثبت در دو ستون آخر یعنی بدترشدن RMS.

{table(['شرایط','پایه صفر، °','قبلی +۶، °','ترکیبی جدید، °','تغییر نسبت به صفر','تغییر نسبت به +۶'],rms)}

نسبت به پایهٔ صفر، کاهش میانگین هندسی RMS **{decision['comparisons'][0]['geometric_mean_rms_reduction']*100:.2f}٪** است، اما سناریوی شش‌قدمی کم‌اصطکاک **۲۰٫۸۸٪** پسرفت دارد. نسبت به کنترل ثابت +۶ mm، میانگین هندسی **۰٫۸۰٪ بدتر** و سناریوی اصطکاک ۰٫۷۲ و هل +۱۱ N **۱۸٫۱۳٪ بدتر** است. هر دو از سقف ۱۰٪ بدترشدنِ تک‌سناریو عبور می‌کنند؛ مقایسه با +۶ شرط حداقل بهبود ۵٪ را نیز رد می‌کند. این درصدها تغییر خطای زاویه‌اند، نه تغییر احتمال سقوط. میانگین این شش شرایط تازه را نباید با میانگین شش شرایط متفاوت PR #87 مستقیماً یکی دانست.

## قدم، زمان و توقف پایانی

عدد قدم برای هر سه نسخه یکسان است. مدت فازهای حرکت و توقف در همهٔ جفت‌ها یکسان ماند؛ دوقدم ۱۷ ثانیه و شش‌قدم ۴۱ ثانیه، به‌علاوهٔ آماده‌سازی مشترک دوثانیه‌ای که داخل RMS حرکت نیست. هیچ زمان اضافی برای آرام‌شدن داده نشد. بیشینهٔ گشتاور نرمال‌شده از ۱ عبور نکرد؛ بعضی اجراها به همان سقف می‌رسند.

{table(['شرایط','قدم هر نسخه','مدت حرکت، s','سرعت نهایی صفر','سرعت نهایی +۶','سرعت نهایی جدید'],speeds)}

معیار ازقبل موجود، بیشینهٔ قدرمطلق سرعت تمام درجه‌های آزادی در پایان کمتر از ۰٫۰۵ است؛ واحد انتقال ریشه m/s و واحد مفصل‌ها و چرخش ریشه rad/s است. تمام مقادیر بیشینهٔ جدول، مفصل دورانی‌اند. دادهٔ نام و سرعت نهایی هر ۶۱ درجهٔ آزادی در فایل هر اجرا ثبت شده؛ بیشینهٔ نیم‌ثانیهٔ آخر نیز صرفاً به‌عنوان تشخیص اضافی حفظ شده است. این تشخیص معیار قبولی جدید یا جایگزین معیار قبلی نیست.

دو شکست سرعت (`known_tail--baseline` و `known_tail--tail0`) با وجود اتمام قدم‌ها حفظ شدند. در این ۳۰ اجرا شکست حل‌گر، تماس غیرپا، حد مفصل یا نگهبان کجی رخ نداد. این نبود شکست در دامنهٔ محدود، اثبات ایمنی در شرایط دیگر نیست.

## اعتبارسنجی و حفظ نسخهٔ اصلی

- ۳۴ آزمون واحد/رگرسیون گذشتند؛ موارد تازه شامل جداسازی checkpoint، عدم بازنویسی حالت، سقف گشتاور، برابری کنترل غیرفعال و رد ارتقا با یک پسرفت، سرعت نامجاز یا وقت اضافه هستند.
- هر ۳۰ هش trace، انتگرال زمانی RMS، جمع مدت فازها و تمام سرعت‌های نهایی بررسی شدند.
- هر {audit['unchanged_parent_file_count']} فایل موجود در والد، شامل مدل، runtime، کنترل‌کننده و نتایج ناموفق قبلی، با بایت‌های محلی یکسان‌اند. `promotion-decision.json` قبلی نیز تغییر نکرد.
- اجرای اصلی با Python 3.12.14، MuJoCo 3.11.0، NumPy 2.3.5، SciPy 1.17.0، OSQP 1.0.5 و هستهٔ SkylakeX تک‌رشته‌ای انجام شد.
- دو اجرای محلی Haswell هر دو قدم و توقف را گذراندند؛ RMS هل برای صفر ۰٫۲۸۱۳۹۵ و برای ترکیبی ۰٫۳۷۷۴۲۶ بود. این فقط بررسی قابلیت اجرا در هستهٔ دیگر است؛ برابری عددی با SkylakeX یا بهبود عملکرد اثبات نشد. GitHub Actions برای این شاخه اجرا نشده است؛ گردش‌کار آماده است.

## تصمیم

`performance_gate_pass=false`، `promotion_allowed=false` و `native_apply_allowed=false`. نسخهٔ ترکیبی هنوز اصلاح پذیرفته‌شدهٔ تعادل نیست. شواهد، کنارگذاشتن محو بایاس/میرایی عمومی به‌عنوان راه‌حل کافی را توجیه می‌کنند. بررسی بعدی باید گذار تماس و تقسیم بار در فرود آخر و بازخورد مرکز جرم/سرعت دم را به‌صورت یک مسئلهٔ کوپل‌شده هدف بگیرد؛ این پیشنهاد در این نوبت پیاده نشده است. هیچ تغییری به بدن اصلی، شاخهٔ اصلی یا checkpoint زنده منتقل نشده است.

## بازتولید

از ریشهٔ همین شاخه، با وابستگی‌های `requirements-trial.txt` و پوشهٔ خروجی تازه:

```sh
export OPENBLAS_CORETYPE=SkylakeX OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python -m examples.nasuraya_research.articulated.landing_study freeze --output evidence/reproduction-landing
python -m examples.nasuraya_research.articulated.landing_study run --output evidence/reproduction-landing --case known_push --variant baseline
```

برای تکمیل، `run` را برای تمام جفت‌های `diagnostics × diagnostic_variants` و `holdouts × holdout_variants` در `protocol.json` اجرا کنید؛ سپس `summarize` و `audit_landing_study --output` را روی همان پوشه اجرا کنید. فایل کامل یا نیمه‌کامل جایگزین نمی‌شود؛ تکرار در پوشهٔ تازه است. برای گزارش، `python -m examples.nasuraya_research.articulated.report_landing_study --output evidence/reproduction-landing --doc docs/reproduction-landing-fa.md` (نیازمند matplotlib).

منابع: [PR #87](https://github.com/zurvanproject/zohraya/pull/87)، [PR #82](https://github.com/zurvanproject/zohraya/pull/82) و فایل‌های JSON/trace این بسته. سطح صاف و هندسهٔ صلب ساده با بازخورد کامل شبیه‌ساز، حدود کاربرد این نتایج‌اند.
'''
    doc.write_text(text)
    # Small self-contained HTML for the review bundle; no external font/assets.
    import re
    def inline(line):
        line=html.escape(line)
        line=re.sub(r'`([^`]+)`',r'<code>\1</code>',line)
        line=re.sub(r'\*\*([^*]+)\*\*',r'<strong>\1</strong>',line)
        return re.sub(r'\[([^]]+)\]\((https://[^)]+)\)',r'<a href="\2">\1</a>',line)
    parts=[];code=[];in_code=False;in_table=False;in_list=False
    for line in text.splitlines():
        if line.startswith('```'):
            if in_code:parts.append('<pre><code>'+html.escape('\n'.join(code))+'</code></pre>');code=[]
            in_code=not in_code;continue
        if in_code:code.append(line);continue
        if in_table and not line.startswith('|'):
            parts.append('</tbody></table>');in_table=False
        if in_list and not line.startswith('- '):parts.append('</ul>');in_list=False
        if line.startswith('|'):
            cells=[c.strip() for c in line.strip('|').split('|')]
            if all(set(c)<=set('-: ') for c in cells):continue
            if not in_table:
                parts.append('<table><thead><tr>'+''.join('<th>'+inline(c)+'</th>' for c in cells)+'</tr></thead><tbody>')
                in_table=True
            else:parts.append('<tr>'+''.join('<td>'+inline(c)+'</td>' for c in cells)+'</tr>')
        elif line.startswith('## '):parts.append('<h2>'+inline(line[3:])+'</h2>')
        elif line.startswith('# '):parts.append('<h1>'+inline(line[2:])+'</h1>')
        elif line.startswith('- '):
            if not in_list:parts.append('<ul>');in_list=True
            parts.append('<li>'+inline(line[2:])+'</li>')
        elif line.strip():parts.append('<p>'+inline(line)+'</p>')
    if in_table:parts.append('</tbody></table>')
    if in_list:parts.append('</ul>')
    body='\n'.join(parts)
    image=base64.b64encode((folder/'comparison.png').read_bytes()).decode()
    body=body.replace('<h2>حذف مؤلفه‌ها',f'<figure><img alt="Measured comparison" src="data:image/png;base64,{image}"></figure><h2>حذف مؤلفه‌ها')
    page='''<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>آزمایش فرود و توقف ناسورایا</title><style>body{margin:0;background:#f4f4ee;color:#19303b;font:17px/1.95 Tahoma,Arial,sans-serif}main{max-width:1100px;margin:auto;background:white;padding:38px}h1{font-size:29px;line-height:1.6;color:#123e4b}h2{margin-top:38px;font-size:23px}p,li{max-width:98ch}table{display:block;overflow-x:auto;border-collapse:collapse;font-size:14px;margin:24px 0}th,td{border:1px solid #d6e1e2;padding:9px 12px;white-space:nowrap}th{background:#e8f2f2}tr:nth-child(even){background:#f8faf9}pre{direction:ltr;text-align:left;background:#f2f5f5;padding:18px;overflow:auto;font-size:13px;line-height:1.6}code{unicode-bidi:embed;direction:ltr}img{width:100%;height:auto}figure{margin:24px 0}a{color:#147d92}@media(max-width:640px){main{padding:20px}body{font-size:16px}h1{font-size:25px}}@media print{main{padding:0}body{font-size:12px}h2{break-after:avoid}tr{break-inside:avoid}}</style><main>'''+body+'</main></html>'
    (folder/'Nasuraya_Landing_Settling_Report_FA.html').write_text(page)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--doc',type=Path,required=True)
    a=p.parse_args();render(a.output,a.doc)
