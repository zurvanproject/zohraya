"""Pinned, source-attributed text memory; no native experience or action import.

Original sources remain authored notes or verbatim caller text. Loading/search
never converts their content into observed software outcomes or verified facts.
"""
from contextlib import closing
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unicodedata

SCHEMA = 'nasuraya.sourced-memory/1'
MAX_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 1024 * 1024
MAX_SOURCES = 16
MAX_RECORDS = 512
LINES_PER_RECORD = 24
KINDS = {'authored_continuity_note', 'verbatim_user_message'}
SOURCE_FIELDS = {'id', 'source_kind', 'locator', 'library_file_id', 'file_id',
                 'file_name', 'version', 'text'}


class SourceMemoryBlocked(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise SourceMemoryBlocked(reason)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def text_digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON field')
            result[key] = value
        return result
    def constant(value):
        raise SourceMemoryBlocked('non-finite JSON number')
    result = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    canonical(result)  # Also rejects overflow such as 1e999.
    return result


def _sources(sources, *, stored):
    require(isinstance(sources, list) and 1 <= len(sources) <= MAX_SOURCES,
            '1..16 explicit source records required')
    seen = set()
    for source in sources:
        require(isinstance(source, dict) and set(source) ==
                SOURCE_FIELDS | ({'sha256'} if stored else set()), 'exact source fields required')
        require(isinstance(source['id'], str) and
                re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', source['id']), 'bounded source ID required')
        require(source['id'] not in seen, 'duplicate source ID'); seen.add(source['id'])
        require(isinstance(source['source_kind'], str) and source['source_kind'] in KINDS,
                'unknown source kind')
        for key in ('locator', 'file_name'):
            require(isinstance(source[key], str) and 0 < len(source[key]) <= 2048,
                    'explicit bounded source locator and filename required')
        for key in ('library_file_id', 'file_id'):
            require(source[key] is None or
                    (isinstance(source[key], str) and 0 < len(source[key]) <= 256),
                    'source IDs must be explicit strings or null')
        require(source['version'] is None or
                (type(source['version']) is int and source['version'] >= 0) or
                (isinstance(source['version'], str) and 0 < len(source['version']) <= 256),
                'source version must be explicit or null')
        require(isinstance(source['text'], str) and bool(source['text'].strip()) and
                len(source['text'].encode('utf-8')) <= MAX_SOURCE_BYTES,
                'nonempty UTF-8 source text up to 1 MiB required')
        if stored:
            require(source['sha256'] == text_digest(source['text']), 'source text checksum mismatch')
    return sources


def _records(sources):
    records = []
    for source in sources:
        lines = source['text'].splitlines(keepends=True)
        for start in range(0, len(lines), LINES_PER_RECORD):
            end = min(start + LINES_PER_RECORD, len(lines))
            records.append(dict(id=source['id'] + ':' + str(start + 1) + '-' + str(end),
                                source_id=source['id'], start_line=start + 1, end_line=end,
                                text=''.join(lines[start:end])))
    require(len(records) <= MAX_RECORDS, 'source memory exceeds 512 exact line-span records')
    return records


def build_archive(sources):
    """Build a new explicit text archive; retain exact text without summarizing."""
    _sources(sources, stored=False)
    copied = [dict(source, sha256=text_digest(source['text'])) for source in sources]
    value = dict(schema=SCHEMA, sources=copied, records=_records(copied))
    encoded = canonical(dict(value=value, sha256=digest(value))) + '\n'
    require(len(encoded.encode('utf-8')) <= MAX_BYTES, 'source memory exceeds 8 MiB')
    return dict(value=value, sha256=digest(value))


def export_archive(sources, destination):
    """Atomically create a new private archive; never replace an existing file."""
    bundle = build_archive(sources)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.sourced-memory-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(canonical(bundle) + '\n'); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)
    return dict(archive_sha256=bundle['sha256'], source_count=len(bundle['value']['sources']),
                record_count=len(bundle['value']['records']), content_kind='source_attributed_text_only',
                body_cycles_executed=0, learning_updates=0)


def load_archive(path, expected_sha256):
    """Verify the independent archive pin, exact sources and exact line spans."""
    require(isinstance(expected_sha256, str) and re.fullmatch(r'[0-9a-f]{64}', expected_sha256),
            'independently retained source-memory SHA-256 required')
    with Path(path).open('rb') as stream:
        encoded = stream.read(MAX_BYTES + 1)
    require(len(encoded) <= MAX_BYTES, 'source memory exceeds 8 MiB')
    bundle = strict_json(encoded.decode('utf-8'))
    require(isinstance(bundle, dict) and set(bundle) == {'value', 'sha256'}, 'unknown source-memory envelope')
    require(digest(bundle['value']) == bundle['sha256'] == expected_sha256,
            'source memory differs from pinned export')
    value = bundle['value']
    require(isinstance(value, dict) and set(value) == {'schema', 'sources', 'records'} and
            value['schema'] == SCHEMA, 'unsupported source-memory schema')
    _sources(value['sources'], stored=True)
    require(canonical(value['records']) == canonical(_records(value['sources'])),
            'source record text or line spans differ from originals')
    return bundle


def normalize(text):
    text = unicodedata.normalize('NFKC', text).translate(str.maketrans({
        'ي': 'ی', 'ى': 'ی', 'ك': 'ک', 'ۀ': 'ه', 'ة': 'ه',
        '\u200c': ' ', '\u200d': ' ', '\u0640': ''}))
    for alphabet in ('٠١٢٣٤٥٦٧٨٩', '۰۱۲۳۴۵۶۷۸۹'):
        text = text.translate(str.maketrans(alphabet, '0123456789'))
    return ''.join(c for c in text.casefold() if not unicodedata.category(c).startswith('M'))


def search(path, expected_sha256, query, max_results=10):
    require(isinstance(query, str) and 1 <= len(query) <= 256, 'bounded explicit text query required')
    terms = re.findall(r'[^\W_]+', normalize(query), flags=re.UNICODE)
    require(1 <= len(terms) <= 8 and all(len(t) <= 80 for t in terms), '1..8 bounded word tokens required')
    require(type(max_results) is int and 1 <= max_results <= 32, '1..32 results required')
    bundle = load_archive(path, expected_sha256); value = bundle['value']
    records = value['records']; by_id = {s['id']: s for s in value['sources']}
    with closing(sqlite3.connect(':memory:')) as db:
        db.execute("CREATE VIRTUAL TABLE memory USING fts5(text, tokenize='unicode61 remove_diacritics 0')")
        db.executemany('INSERT INTO memory(rowid,text) VALUES(?,?)',
                       [(i + 1, normalize(r['text'])) for i, r in enumerate(records)])
        expression = ' AND '.join('"' + t.replace('"', '""') + '"' for t in dict.fromkeys(terms))
        rows = db.execute('SELECT rowid FROM memory WHERE memory MATCH ? ORDER BY bm25(memory),rowid LIMIT ?',
                          (expression, max_results)).fetchall()
    hits = []
    for (rowid,) in rows:
        r = records[rowid - 1]; source = by_id[r['source_id']]
        hits.append(dict(record_id=bundle['sha256'] + '/' + r['id'], text=r['text'],
                         start_line=r['start_line'], end_line=r['end_line'],
                         source={k: v for k, v in source.items() if k != 'text'},
                         status='historical_context_only', verified_fact=False,
                         native_outcome_recorded=False))
    return dict(schema='nasuraya.sourced-memory-search/1', archive_sha256=bundle['sha256'], hits=hits,
                source_count=len(value['sources']), record_count=len(records),
                body_cycles_executed=0, learning_updates=0,
                scope='source-attributed historical text; no native observation, permission or belief promotion')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--query', required=True)
    parser.add_argument('--max-results', type=int, default=10)
    args = parser.parse_args()
    try:
        result = search(args.archive, args.expected_sha256, args.query, args.max_results)
    except (ValueError, OSError) as exc:
        print(json.dumps(dict(status='rejected', reason=str(exc)), ensure_ascii=False)); return 1
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
