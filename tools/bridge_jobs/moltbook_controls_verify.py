"""Perform at most one verification for the approved Sokimi reply, no content creation."""
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

POST_ID = 'e97c71c8-49db-424e-b0ec-d913e883044f'
EXPECTED_COMMENT = ''
CHALLENGE_SHA = 'baab51b651d9a82f55498d13512ec613e5dc6df9a47c262b79237ec31ca4a9fc'
BODY_SHA = '54d89db1a32e6fe64ad7597f2eefdf677f694c2739ee061aa87d30dff5b5e50b'
ANSWER = '42.00'
COMMENTS = '/api/v1/posts/' + POST_ID + '/comments?sort=new&limit=100'

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



def find_comment(payload, comment):
    if (payload.get('success') is False or payload.get('post_id') != POST_ID or
            payload.get('has_more') is not False or not isinstance(payload.get('comments'), list)):
        raise ValueError('Incomplete comments')
    matching = [c for c in payload['comments'] if c.get('id') == comment]
    if not matching:
        return None
    if len(matching) != 1:
        raise ValueError('Ambiguous comment')
    c = matching[0]
    if (c.get('post_id') != POST_ID or c.get('parent_id') is not None or
            c.get('author', {}).get('name', '').lower() != 'nasuraya' or
            hashlib.sha256(c.get('content', '').encode('utf-8')).hexdigest() != BODY_SHA or
            c.get('is_deleted') is not False or c.get('is_spam') is not False):
        raise ValueError('Comment mismatch')
    return c.get('verification_status') or 'unknown'


def verify(root, client):
    if not re.fullmatch(r'-?[0-9]+\.[0-9]{2}', ANSWER):
        return 'BAD_ANSWER_FORMAT_NO_WRITE'
    ledger = json.loads((root / 'reply.json').read_text(encoding='utf-8'))
    comment = ledger.get('comment_id')
    if (not isinstance(comment, str) or
            not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', comment)
            or (EXPECTED_COMMENT and comment != EXPECTED_COMMENT)):
        return 'INVALID_LEDGER_ID_NO_WRITE'
    if (ledger.get('state') != 'submitted'
            or ledger.get('post_id') != POST_ID or ledger.get('body_sha256') != BODY_SHA):
        return 'LEDGER_MISMATCH_NO_WRITE'
    me, _ = client.request('GET', '/api/v1/agents/me')
    if me.get('agent', {}).get('name', '').lower() != 'nasuraya':
        return 'ACCOUNT_MISMATCH_NO_WRITE'
    listing, date = client.request('GET', COMMENTS)
    status = find_comment(listing, comment)
    if status in ('verified', 'not_required'):
        return 'ALREADY_CONFIRMED=' + comment
    if status not in ('pending', None):
        return 'UNEXPECTED_STATE_NO_WRITE'
    # Pending entries may be hidden; the fixed POST's saved receipt binds this UUID.
    verification = ledger.get('verification') or {}
    challenge = verification.get('challenge_text')
    if not isinstance(challenge, str) or hashlib.sha256(challenge.encode('utf-8')).hexdigest() != CHALLENGE_SHA:
        return 'CHALLENGE_MISMATCH_NO_WRITE=' + comment
    code = verification.get('verification_code')
    if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9_-]{12,256}', code):
        return 'NO_VERIFICATION_CODE'
    expires = datetime.fromisoformat(verification['expires_at'].replace('Z', '+00:00'))
    now = parsedate_to_datetime(date)
    if expires.tzinfo is None or now.tzinfo is None:
        return 'CLOCK_UNAVAILABLE_NO_WRITE'
    if now >= expires:
        return 'EXPIRED_NO_WRITE=' + comment

    marker = root / 'verify_started.json'
    try:
        f = marker.open('x', encoding='utf-8')
    except FileExistsError:
        return 'PRIOR_ATTEMPT_REVIEW_NO_RETRY'
    with f:
        json.dump({'comment_id': comment, 'state': 'started', 'server_date': date}, f)
        f.flush()
        os.fsync(f.fileno())

    response, _ = client.request('POST', '/api/v1/verify',
                                 {'verification_code': code, 'answer': ANSWER})
    if response.get('success') is not True or response.get('content_id') != comment:
        return 'VERIFY_RESPONSE_UNCONFIRMED=' + comment
    try:
        listing, _ = client.request('GET', COMMENTS)
        if find_comment(listing, comment) == 'verified':
            return 'COMMENT_VERIFIED=' + comment
    except Exception:
        pass
    return 'ACCEPTED_AWAITING_PUBLIC_READ=' + comment


def main():
    try:
        root = Path(os.environ['LOCALAPPDATA']) / 'Nasuraya' / 'Moltbook' / 'sokimi_20261107'
        summary = verify(root, Client(existing_key()))
    except urllib.error.HTTPError as exc:
        summary = 'VERIFY_HTTP=' + str(exc.code)
    except Exception:
        summary = 'VERIFY_STOPPED_REVIEW_REQUIRED'
    print(json.dumps({'status': 'ok', 'summary': summary}, separators=(',', ':')))


if __name__ == '__main__':
    main()
