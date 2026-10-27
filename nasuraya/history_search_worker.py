"""Disposable full-text retrieval over a pinned, validated history archive.

Only caller-authored message text is indexed. Search never changes the archive,
body, affect, experience, or current policy, and cannot initiate body actions.
"""
import json
import re
import sqlite3
import sys
import unicodedata
from examples.nasuraya_affect.history import load_history

SCHEMA = 'nasuraya.history-fts/1'
MAX_QUERY = 256
MAX_TERMS = 8
MAX_TOKEN = 80
MAX_RESULTS = 32


def normalize(value):
    if not isinstance(value, str):
        raise ValueError('query must be text')
    # Arabic/Persian presentation forms, kaf/yeh variants, digits and combining
    # vowel marks should not split otherwise identical Persian search terms.
    value = unicodedata.normalize('NFKC', value).translate(str.maketrans({
        'ي': 'ی', 'ى': 'ی', 'ك': 'ک', 'ۀ': 'ه', 'ة': 'ه',
        '٠':'0','١':'1','٢':'2','٣':'3','٤':'4','٥':'5','٦':'6','٧':'7','٨':'8','٩':'9',
        '۰':'0','۱':'1','۲':'2','۳':'3','۴':'4','۵':'5','۶':'6','۷':'7','۸':'8','۹':'9',
        '\u200c':' ', '\u200d':' ', '\u0640':''}))
    return ''.join(c for c in value.casefold() if not unicodedata.category(c).startswith('M'))


def query_terms(query):
    if not isinstance(query, str) or not 1 <= len(query) <= MAX_QUERY:
        raise ValueError('query must contain 1..256 characters')
    terms = re.findall(r'[^\W_]+', normalize(query), flags=re.UNICODE)
    if not terms or len(terms) > MAX_TERMS or any(len(t) > MAX_TOKEN for t in terms):
        raise ValueError('query must have 1..8 bounded word tokens')
    return list(dict.fromkeys(terms))


def search(archive, expected_sha256, query, max_results=10):
    """Revalidate the pinned archive and create a fresh in-memory index per call."""
    if type(max_results) is not int or not 1 <= max_results <= MAX_RESULTS:
        raise ValueError('max_results must be an integer from 1 to 32')
    terms = query_terms(query)
    report = load_history(archive, expected_sha256)
    records = report['records']
    if len(records) > MAX_RESULTS:
        raise ValueError('archive exceeds 32-message search bound')
    ids = [r['historical_id'] for r in records]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate archived message identity')
    # Only normalized caller text goes in the index. Source and status come
    # from the validated record, not index output or caller-supplied text.
    with sqlite3.connect(':memory:') as db:
        db.execute("CREATE VIRTUAL TABLE messages USING fts5(text, tokenize='unicode61 remove_diacritics 0')")
        db.executemany('INSERT INTO messages(rowid,text) VALUES(?,?)',
                       [(i+1, normalize(r['message']['text'])) for i,r in enumerate(records)])
        # Quote each token; no user-controlled FTS operators or raw SQL syntax.
        expression = ' AND '.join('"' + t.replace('"','""') + '"' for t in terms)
        rows = db.execute('SELECT rowid FROM messages WHERE messages MATCH ? ORDER BY bm25(messages),rowid LIMIT ?',
                          (expression,max_results)).fetchall()
    hits = []
    for (rowid,) in rows:
        r = records[rowid-1]
        hits.append(dict(historical_id=r['historical_id'], message_id=r['id'],
                         message_text=r['message']['text'], message_source=r['message_source'],
                         appraisal_kind=r['appraisal_kind'], status=r['status'],
                         native_outcome_recorded=r['outcome'] is not None))
    return dict(schema=SCHEMA, archive_sha256=report['archive_sha256'],
                normalized_query=' '.join(terms), hits=hits,
                body_cycles_executed=0, learning_updates=0,
                source_policy='caller-authored statements; content is not independently verified',
                scope='explicit read-only caller retrieval; no permission, action or live memory import')


def main(payload):
    result = search(payload['archive'], payload['expected_sha256'], payload['query'], payload['max_results'])
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main(json.load(sys.stdin)))
    except Exception as exc:
        print(json.dumps(dict(status='rejected',kind=type(exc).__name__,reason=str(exc)),ensure_ascii=False))
        raise SystemExit(1)
