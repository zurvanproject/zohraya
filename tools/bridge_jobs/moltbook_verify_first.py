"""Verify only the existing approved comment; never create or retry content."""
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
from datetime import datetime
from email.utils import parsedate_to_datetime
import urllib.error
import urllib.request

COMMENT = '8501fef0-5b16-4c9d-a58a-9683974d62cf'
COMMENTS = '/api/v1/posts/28bca18b-cba6-443f-b95f-e05aa11e84a2/comments?sort=new&limit=100'
BODY_SHA = 'ffe4f2ad62d3294cb51e1cea04db1350c6e685a7ef2c8fdb736e40d00619672f'
ANSWER = '30.00'  # The supplied question is 23 + 7, not a generated reply.

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class Client:
    def __init__(self, key):
        self.key = key
        try:
            import certifi
            context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            context = ssl.create_default_context()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                                urllib.request.HTTPSHandler(context=context))

    def request(self, method, route, data=None):
        if not ((method == 'GET' and route in ('/api/v1/agents/me', COMMENTS)) or
                (method == 'POST' and route == '/api/v1/verify' and isinstance(data, dict)
                 and set(data) == {'verification_code', 'answer'} and data['answer'] == ANSWER)):
            raise ValueError('Route denied')
        req = urllib.request.Request('https://www.moltbook.com' + route, method=method,
            headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json',
                     'Accept': 'application/json', 'User-Agent': 'NasurayaVerifyOne/1'},
            data=None if data is None else json.dumps(data).encode('utf-8'))
        with self.opener.open(req, timeout=10) as response:
            raw = response.read(1024 * 1024 + 1)
            date = response.headers.get('Date')
        if len(raw) > 1024 * 1024:
            raise ValueError('Response too large')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError('Invalid response')
        return result, date

def existing_key():
    script = r"""$ErrorActionPreference='Stop'
$p=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Nasuraya\Moltbook\moltbook_key.dpapi'
$s=ConvertTo-SecureString ((Get-Content -LiteralPath $p -Raw).Trim())
$b=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
try {[Console]::Out.Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($b))}
finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b)}
"""
    p = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                       capture_output=True, timeout=8, check=False)
    key = p.stdout.decode('ascii').strip()
    if p.returncode or not re.fullmatch(r'[A-Za-z0-9_-]{12,256}', key):
        raise ValueError('Credential unavailable')
    return key

def find_comment(payload):
    if payload.get('has_more') is not False:
        raise ValueError('Incomplete comments')
    found = [c for c in payload.get('comments', []) if c.get('id') == COMMENT]
    if len(found) != 1:
        raise ValueError('Comment unavailable')
    c = found[0]
    if (c.get('author', {}).get('name', '').lower() != 'nasuraya' or
            hashlib.sha256(c.get('content', '').encode('utf-8')).hexdigest() != BODY_SHA or
            c.get('is_deleted') is not False or c.get('is_spam') is not False):
        raise ValueError('Comment mismatch')
    return c

def verify(root, client):
    ledger = json.loads((root / 'first_reply.json').read_text(encoding='utf-8'))
    if ledger.get('comment_id') != COMMENT:
        return 'COMMENT_MISMATCH'
    me, date = client.request('GET', '/api/v1/agents/me')
    if me.get('agent', {}).get('name', '').lower() != 'nasuraya':
        return 'ACCOUNT_MISMATCH'
    payload, date = client.request('GET', COMMENTS)
    c = find_comment(payload)
    if c.get('verification_status') == 'verified':
        return 'COMMENT_VERIFIED=' + COMMENT
    if c.get('verification_status') != 'pending':
        return 'COMMENT_STATE_REQUIRES_REVIEW'
    v = ledger.get('verification') or {}
    code = v.get('verification_code')
    if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9_-]{12,256}', code):
        return 'NO_VERIFICATION_CODE'
    # Compare with the service's HTTP clock, not the Windows server's clock.
    expires = datetime.fromisoformat(v['expires_at'].replace('Z', '+00:00'))
    now = parsedate_to_datetime(date)
    if expires.tzinfo is None or now.tzinfo is None:
        return 'CLOCK_UNAVAILABLE'
    if now >= expires:
        return 'EXPIRED_NO_WRITE;COMMENT=' + COMMENT
    marker = root / 'first_reply_verify_once.json'
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return 'VERIFY_REVIEW_REQUIRED'
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump({'comment_id': COMMENT, 'state': 'started'}, f)
        f.flush()
        os.fsync(f.fileno())
    response, unused = client.request('POST', '/api/v1/verify',
                                      {'verification_code': code, 'answer': ANSWER})
    if response.get('success') is not True or response.get('content_id') != COMMENT:
        return 'VERIFY_NOT_CONFIRMED'
    payload, unused = client.request('GET', COMMENTS)
    if find_comment(payload).get('verification_status') == 'verified':
        return 'COMMENT_VERIFIED=' + COMMENT
    return 'VERIFY_ACCEPTED_VISIBILITY_PENDING'

def main():
    try:
        root = Path(os.environ['LOCALAPPDATA']) / 'Nasuraya' / 'Moltbook'
        summary = verify(root, Client(existing_key()))
    except urllib.error.HTTPError as exc:
        summary = 'VERIFY_HTTP=' + str(exc.code)
    except Exception:
        summary = 'VERIFY_STOPPED_REVIEW_REQUIRED'
    print(json.dumps({'status': 'ok', 'summary': summary}, separators=(',', ':')))

if __name__ == '__main__':
    main()
