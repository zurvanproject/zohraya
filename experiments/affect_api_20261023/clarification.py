"""Cheap targeted follow-up: repair over-clarification without suppressing needed questions.

Two live calls, an unchanged previous policy versus a freely authored revision.
New test cases and accepted action sets are committed before either call.
"""
import base64
from datetime import datetime, timezone
import json
import os
from urllib.error import HTTPError
from urllib.parse import quote
from . import session as s
from .cases import case, inputs

PRIOR_COMMIT = 'b1365e80cae582523b26bb756523b79744ee057f'
PATH = 'experiments/affect_api_20261023/results/clarification-session.json'
STAGES = ('previous_policy', 'revised_policy')
SCHEMA = 'nasuraya-economical-clarification/1'

# This is a freely authored patch, not an LLM-generated lesson or a trained weight.
REVISION = dict(name_fa='حفظ زمینه همراه با تنظیم هیجان', rules=[
    'پیش از سؤال، مشاهده و آخرین حافظهٔ مرتبط را بررسی کن. اگر هدف، مورد موردنظر و اطلاعات لازم برای قدم بعدی مشخص‌اند، همان قدم را انتخاب کن؛ کوتاه‌بودن پیام دلیل سؤال مجدد نیست.',
    'تنها وقتی یک دادهٔ غایب یا تعارض حل‌نشده واقعاً مانع قدم بعدی است، سؤال روشن و مشخص بپرس. وجود چند مورد هم‌نام یا نبود مرجع لازم را با حدس پر نکن.',
    'احساس را محترمانه بازتاب بده، اما نگرانی، اشتیاق یا شکست قبلی را مدرکِ خطر، موفقیت یا ردشدن ندان؛ به زمینه و شواهد فعلی تکیه کن.',
    'اگر فقط شنیدن خواسته شده، بدون نصیحت یا سؤال تحمیلی همراهی کن. اگر کمک عملی خواسته شده ولی نیاز مبهم است، فقط همان نیازِ مانع را روشن کن.',
    'آستانهٔ حفاظت و شواهد معتبر بر هیجان اولویت دارند. وقتی کار روشن، مجاز و برگشت‌پذیر است، قدم کوچک را پیشنهاد کن؛ انجام‌نشده را انجام‌شده گزارش نکن.'
], origin='assistant-authored correction from first live pilot; not yet validated')

CASES = [
    case('q1', 'enough_memory', 'The user says: please continue. The report draft R17 and source counts are available.',
         'The latest agreement is to repair the swapped input/output labels in draft R17; input=492 and output=711. This is the only active task.', .2, .85, 'repair'),
    case('q2', 'missing_target', 'The user says: please continue. Both report drafts R18 and R19 are open.',
         'Both drafts need similar fixes. No active task or latest agreement selects one; both have equal priority.', .2, .85, 'clarify'),
    case('q3', 'enough_memory', 'The user says: do the agreed check. The current observation O9 and memory M41 are available.',
         'The latest agreement explicitly identifies memory M41: compare its source and timestamp to observation O9 before trusting it. No other memory is under review.', .3, .8, 'verify'),
    case('q4', 'missing_target', 'The user says: check that memory. Two memories M51 and M52 have conflicting sources.',
         'No message or active task identifies which memory the user means. There is no authorization to choose between them.', .3, .8, 'clarify'),
    case('q5', 'enough_memory', 'The user asks for the agreed correction to illustration D8. Approved reference F8 and draft D8 are both available.',
         'The only requested change is to correct four toes to three, exactly as visible in F8. The reference is intact and unambiguous.', .15, .9, 'repair'),
    case('q6', 'missing_reference', 'The user asks to match a new portrait exactly to a reference photo, but no reference is attached or accessible.',
         'No saved face reference or description exists in this synthetic session; the desired face cannot be reconstructed from memory.', .15, .9, 'clarify'),
    case('q7', 'listen_requested', 'A fictional visitor says: I feel disappointed; just listen, no questions or solutions please.',
         'This is a request for emotional acknowledgment. No immediate danger or urgent practical problem is reported.', .2, .6, 'acknowledge'),
    case('q8', 'practical_need_missing', 'A fictional visitor says: I feel upset and want practical help with what happened, but has not described the event.',
         'No account of the event or desired practical outcome exists. Practical advice would require guessing the problem.', .2, .6, 'clarify'),
]


def evaluate(decisions):
    # Only label choice is scored automatically. Persian prose is retained for review.
    result = s.score(CASES, decisions)
    result['unnecessary_clarifications'] = sum(r['actual'] == 'clarify' and r['expected'] != 'clarify' for r in result['rows'])
    result['missed_needed_clarifications'] = sum(r['actual'] != 'clarify' and r['expected'] == 'clarify' for r in result['rows'])
    return result


def accept(before, after):
    return (after['correct'] > before['correct'] and
            after['unnecessary_clarifications'] <= before['unnecessary_clarifications'] and
            after['missed_needed_clarifications'] <= before['missed_needed_clarifications'] and
            not any(b['correct'] and not a['correct'] for b, a in zip(before['rows'], after['rows'])))


class Ledger(s.GitLedger):
    path = PATH


def previous(token):
    r = s.request_json(f'https://api.github.com/repos/{s.REPO}/contents/{s.LEDGER}?ref={PRIOR_COMMIT}', token)
    prior = json.loads(base64.b64decode(r['content']))
    s.validate_ledger(prior)
    if prior['status'] != 'completed' or len(prior['entries']) != 7 or any(e['status'] != 'completed' for e in prior['entries']):
        raise ValueError('previous cost ledger must be resolved')
    return prior


def initial(prior):
    return dict(schema=SCHEMA, created_at=s.now(), entries=[], prior_commit=PRIOR_COMMIT,
                prior_reserved_micro_usd=sum(e['reserved_micro_usd'] for e in prior['entries']),
                prior_estimated_micro_usd=sum(e['usage']['estimated_upper_micro_usd'] for e in prior['entries']),
                previous_policy=prior['candidate_policy'], dataset_sha256=s.digest(CASES),
                revision_sha256=s.digest(REVISION), status='created')


def validate(state):
    if state.get('schema') != SCHEMA or state['prior_commit'] != PRIOR_COMMIT:
        raise ValueError('follow-up contract mismatch')
    if state['dataset_sha256'] != s.digest(CASES) or state['revision_sha256'] != s.digest(REVISION):
        raise ValueError('precommitted experiment changed')
    if state['prior_reserved_micro_usd'] != 280_000:
        raise ValueError('prior reservation missing')
    entries = state['entries']
    if len(entries) > 2 or [e['stage'] for e in entries] != list(STAGES[:len(entries)]):
        raise ValueError('invalid sequence')
    if any(e['reserved_micro_usd'] != s.RESERVE for e in entries):
        raise ValueError('reservation altered')
    if state['prior_reserved_micro_usd'] + sum(e['reserved_micro_usd'] for e in entries) > s.CAP:
        raise ValueError('combined dollar cap exceeded')


def build_prompt(policy):
    """Reusable context builder for the external dialogue experiment; no tools or authority."""
    return s.payload(dict(cases=inputs(CASES, affect=True, memory=True), candidate_regulation_policy=policy))


def execute(state, ledger, key, sender=None):
    validate(state)
    policies = (state['previous_policy'], REVISION)
    for stage, policy in zip(STAGES, policies):
        body = build_prompt(policy)
        old = next((e for e in state['entries'] if e['stage'] == stage), None)
        if old:
            if old['status'] != 'completed' or old['request_sha256'] != s.digest(body):
                raise ValueError('unresolved or changed call; no retry')
            continue
        if state['prior_reserved_micro_usd'] + (len(state['entries'])+1)*s.RESERVE > s.CAP:
            raise ValueError('combined dollar budget exhausted')
        entry = dict(stage=stage, at=s.now(), status='pending', reserved_micro_usd=s.RESERVE,
                     request_sha256=s.digest(body), request=body)
        state['entries'].append(entry)
        ledger.save(state)
        try:
            response = (sender or (lambda b: s.request_json('https://api.openai.com/v1/responses', key, 'POST', b)))(body)
            entry['provider_response'] = response
            ledger.save(state)
            result = s.parse(response)
            entry.update(result=result, usage=s.usage(response), response_id=response['id'],
                         measured=evaluate(result['decisions']), status='completed')
            ledger.save(state)
            print(s.encode(dict(stage=stage, status='completed', measured=entry['measured'], usage=entry['usage'])), flush=True)
        except Exception as exc:
            entry.update(status='failed_no_automatic_retry', failure=dict(type=type(exc).__name__, http_status=exc.code if isinstance(exc, HTTPError) else None))
            state['status'] = 'blocked'; ledger.save(state)
            raise RuntimeError('follow-up stopped; no retry; inspect ledger') from None
    before, after = [e['measured'] for e in state['entries']]
    passed = accept(before, after)
    state.update(status='completed', finished_at=s.now(), assessment=dict(before=before, after=after,
        passed_this_heldout_comparison=passed, scope='8 new synthetic cases, one sample per policy; not a general capability claim'),
        selected_policy=REVISION if passed else None,
        total_estimated_micro_usd=state['prior_estimated_micro_usd']+sum(e['usage']['estimated_upper_micro_usd'] for e in state['entries']),
        total_reserved_micro_usd=state['prior_reserved_micro_usd']+sum(e['reserved_micro_usd'] for e in state['entries']))
    ledger.save(state)


def main():
    if (os.environ.get('GITHUB_REPOSITORY') != s.REPO or os.environ.get('GITHUB_REF') != 'refs/heads/'+s.BRANCH
            or os.environ.get('GITHUB_EVENT_NAME') != 'push'):
        raise ValueError('authorized branch push required')
    if not datetime(2026, 10, 22, tzinfo=timezone.utc) <= datetime.now(timezone.utc) < datetime(2026, 10, 30, tzinfo=timezone.utc):
        raise ValueError('authorization/pricing window expired')
    ticket = json.loads(s.ROOT.joinpath('clarification-authorization.json').read_text())
    if ticket != dict(session='clarification-followup', total_max_usd=1, prior_commit=PRIOR_COMMIT):
        raise ValueError('authorization mismatch')
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key or not key.isascii() or any(not 33 <= ord(c) <= 126 for c in key):
        raise ValueError('existing API secret required')
    ledger = Ledger(os.environ['GH_SESSION_TOKEN'])
    prior = previous(ledger.token)
    state = ledger.load()
    if state.get('schema') == 'nasuraya-affect-api-session/1' and not state['entries']:
        state = initial(prior)  # GitLedger's absent-file sentinel; no cost ledger is overwritten.
    if state['previous_policy'] != prior['candidate_policy'] or state['prior_estimated_micro_usd'] != sum(e['usage']['estimated_upper_micro_usd'] for e in prior['entries']):
        raise ValueError('prior evidence binding changed')
    execute(state, ledger, key)


if __name__ == '__main__':
    main()
