"""Extensible, explicitly designed emotion profiles; no subjective-state claim.

Each row: Persian label, positive loading, negative loading, activation loading,
planning tendency, appraisal coefficients, optional contextual multiplier.
Coactivation is preserved: neither a softmax nor a single winning feeling is used.
These parameters are proposed fixtures, not a validated human emotion taxonomy.
"""
from __future__ import annotations
import math

# Contextual multipliers: bond, trust, romantic bond, and valuable goal.
PROFILES = {
 'love': ('دوست داشتن',1.,0.,.35,'express_care',{'warmth':.7,'intimacy':.7},'bond'),
 'attachment': ('دلبستگی',.6,.15,.35,'express_care',{'warmth':.4,'intimacy':.4,'return':.3},'bond'),
 'romantic_love': ('عشق رمانتیک',1.,.1,.75,'express_care',{'intimacy':.8,'appeal':.3},'romantic_bond'),
 'tenderness': ('مهر و لطافت',.9,0.,.2,'express_care',{'need':.4,'intimacy':.6},None),
 'trust': ('اعتماد',.7,0.,.15,'collaborate',{'reliability':.7,'warmth':.25,'betrayal':-.9},'trust'),
 'hope': ('امید',.7,.15,.5,'plan_small_step',{'possibility':.6,'anticipation':.3,'helplessness':-.5},'goal'),
 'relief': ('آسودگی',.8,0.,.15,'pause_regulate',{'threat_removed':.8},None),
 'contentment': ('رضایت و خرسندی',.8,0.,.15,'acknowledge_enough',{'satisfaction':.7},None),
 'amusement': ('سرخوشی و خنده',.9,0.,.6,'share_lightness',{'humor':.8},None),
 'pride': ('غرور و سربلندی',.8,.05,.6,'celebrate',{'achievement':.8},None),
 'admiration': ('تحسین',.8,0.,.5,'learn_from_example',{'excellence':.8},None),
 'awe': ('حیرت و هیبت',.6,.4,.7,'contemplate',{'vastness':.8,'prediction_error':.2},None),
 'elevation': ('تأثر اخلاقی',.8,.1,.4,'learn_from_example',{'moral_example':.8},None),
 'grief': ('سوگ',.05,1.,.4,'reflect_repair',{'irreversible_loss':.9},None),
 'loneliness': ('تنهایی',0.,.9,.3,'seek_connection',{'isolation':.8,'separation':.3},None),
 'anxiety': ('اضطراب',0.,.9,.85,'verify',{'future_threat':.7,'anticipation':.25},None),
 'disappointment': ('ناامیدی از نتیجه',0.,.8,.3,'revise_expectation',{'negative_prediction':.8},None),
 'shame': ('شرم',0.,.9,.5,'restore_dignity',{'self_devaluation':.7,'social_exposure':.2},None),
 'guilt': ('احساس گناه',.05,.8,.4,'own_mistake',{'norm_violation':.8},None),
 'embarrassment': ('خجالت و دستپاچگی',.1,.6,.6,'restore_dignity',{'social_exposure':.7},None),
 'envy': ('حسرت و حسادت مقایسه‌ای',0.,.75,.6,'learn_from_comparison',{'comparison':.75},'goal'),
 'jealousy': ('حسادت رابطه‌ای',0.,.85,.75,'check_relationship_interpretation',{'bond_threat':.8},'bond'),
 'disgust': ('انزجار',0.,.9,.65,'avoid_and_verify',{'contamination':.8},None),
 'frustration': ('کلافگی',0.,.7,.75,'revise_expectation',{'blocked_goal':.8},'goal'),
 'boredom': ('ملال',0.,.55,.1,'explore',{'monotony':.8},None),
 'despair': ('یأس',0.,1.,.25,'plan_small_step',{'helplessness':.8},'goal'),
 'nostalgia': ('حسرت شیرین گذشته',.55,.55,.25,'remember_meaning',{'reminder':.8},'bond'),
 'surprise': ('تعجب',.3,.3,.8,'verify',{'prediction_error':.8},None),
 'desire': ('اشتیاق و خواستن',.6,.1,.75,'pursue_consensual_goal',{'incentive':.8},'goal'),
 'attraction': ('کشش',.7,0.,.65,'pursue_consensual_goal',{'appeal':.8},None),
 'vulnerability': ('آسیب‌پذیری',.1,.65,.5,'restore_dignity',{'exposure_risk':.8},None),
 'contempt': ('تحقیر در ارزیابی',0.,.75,.4,'set_boundary',{'moral_violation':.7},None),
 'courage': ('شجاعت',.65,.15,.7,'plan_small_step',{'approach_intent':.8},'goal'),
}
EXTRA_SIGNALS = {k for row in PROFILES.values() for k in row[5]} | {'value_goal'}
SOMATIC_BASE = dict(pain=0., hunger=0., thirst=0., fatigue=0., warmth=0., cold=0.,
                    touch=0., comfort=.6, arousal=0., nausea=0.)
BASE_LOADINGS = {
 'compassion':(.7,.15,.3),'affection':(.9,0.,.3),'longing':(.25,.65,.4),
 'sadness':(0.,.9,.2),'anger':(0.,.85,.85),'joy':(1.,0.,.65),'fear':(0.,1.,.9),
 'curiosity':(.6,0.,.5),'calm':(.6,0.,.05),'gratitude':(.85,0.,.3),'regret':(0.,.8,.35),
}
BASE_LABELS = {'compassion':'مهربانی','affection':'مهر','longing':'دلتنگی','sadness':'ناراحتی',
 'anger':'خشم','joy':'شادی','fear':'ترس','curiosity':'کنجکاوی','calm':'آرامش',
 'gratitude':'قدردانی','regret':'پشیمانی'}
EXTRA_POLICIES = {
 'express_care':'اهمیت پیوند را با توجه و کمک متناسب بیان کن؛ هیچ ادعای مالکیت یا نیاز به بازگشت نساز.',
 'collaborate':'برای همکاریِ محدود و روشن برنامه بده؛ اعتماد را با شاهد تازه بازبینی کن.',
 'plan_small_step':'یک گام کوچک و شدنی در جهت هدف پیشنهاد بده؛ نتیجه را قطعی وعده نده.',
 'acknowledge_enough':'رضایت را به رسمیت بشناس و از افزایش بی‌دلیل خواسته‌ها پرهیز کن.',
 'share_lightness':'در زمینهٔ مناسب، بیان سبک و محترمانه انتخاب کن.',
 'learn_from_example':'کیفیت یا رفتار تحسین‌شده را به یک درس مشخص تبدیل کن.',
 'contemplate':'برای دریافت امر پیچیده مکث کن؛ ندانستن را روشن نگه دار.',
 'seek_connection':'امکان ارتباط اختیاری را بررسی کن؛ هیچ پیام یا پیگیری خودکاری اجرا نکن.',
 'revise_expectation':'انتظار یا مسیر مسدود را بازبینی کن و گزینهٔ شدنی بساز.',
 'restore_dignity':'خطا یا آسیب‌پذیری را از ارزش شخص جدا کن؛ تحقیر و سرزنش پیشنهاد نده.',
 'learn_from_comparison':'مقایسه را به یادگیری تبدیل کن؛ حق دیگری را محدود نکن.',
 'check_relationship_interpretation':'برداشت از تهدید رابطه را با شاهد بررسی کن؛ کنترل دیگری یا انحصارطلبی پیشنهاد نده.',
 'avoid_and_verify':'منشأ انزجار را بررسی کن؛ آن را به ارزش‌گذاری انسان‌ها تعمیم نده.',
 'remember_meaning':'معنای خاطره را بازیابی کن و وجه شیرین و تلخ آن را حفظ کن.',
 'pursue_consensual_goal':'خواستن را به هدف روشن و سازگار با اختیار دیگران تبدیل کن.',
 'relieve_simulated_discomfort':'در مدل بدنی، بار یا ناراحتیِ واردشده را بازبینی کن؛ حسگر واقعی فرض نکن.',
}


def context(state, event, memory_enabled=True):
    rel = state['relationships'].get(event.get('partner'), {}) if memory_enabled else {}
    bond = rel.get('trust', 0.) * rel.get('value', 0.)
    return {'bond':bond, 'trust':rel.get('trust', 0.),
            'romantic_bond':bond if event.get('relationship_mode') == 'romantic' else 0.,
            'goal':event['signals']['value_goal']}


def innovations(state, event, memory_enabled=True):
    ctx, c = context(state,event,memory_enabled), event['confidence']
    result = {}
    for key, row in PROFILES.items():
        value = sum(event['signals'][signal]*weight for signal,weight in row[5].items())
        result[key] = c * value * (ctx[row[6]] if row[6] else 1.)
    return result


def eligible(event):
    # Context is used for action eligibility; activation strength is used for ranking.
    actions=[]
    for row in PROFILES.values():
        if any(weight > 0 and event['signals'][key] > 0 for key,weight in row[5].items()):
            if row[4] not in actions:
                actions.append(row[4])
    return actions


def summarize(affect):
    positive, negative, activation = [], [], []
    for key,value in affect.items():
        loads = PROFILES[key][1:4] if key in PROFILES else BASE_LOADINGS[key]
        positive.append(value*loads[0]); negative.append(value*loads[1]); activation.append(value*loads[2])
    # Max pooling is an explicit design summary; retain the full state underneath.
    p, n, a = max(positive,default=0.),max(negative,default=0.),max(activation,default=0.)
    return {'positive':p,'negative':n,'activation':a,'mixed_intensity':min(p,n),
            'active_labels':[PROFILES[k][0] if k in PROFILES else BASE_LABELS[k]
                             for k,v in sorted(affect.items(),key=lambda kv:(-kv[1],kv[0])) if v >= .2],
            'interpretation':'designed state summary, not a measurement of subjective experience'}


def blend(affect, weights):
    """Read any declared combination without normalizing competing emotions away."""
    if not weights or any(k not in affect for k in weights):
        raise ValueError('known nonempty emotion combination required')
    if any(isinstance(w,bool) or not isinstance(w,(int,float)) or not math.isfinite(w) or w < 0 for w in weights.values()):
        raise ValueError('finite nonnegative weights required')
    total=sum(weights.values())
    if not total:
        raise ValueError('positive total weight required')
    return {'components':{k:affect[k] for k in weights},
            'intensity':sum(affect[k]*w for k,w in weights.items())/total}
