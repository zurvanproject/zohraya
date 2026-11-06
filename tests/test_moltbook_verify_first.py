import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools/bridge_jobs' / (name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

m = module('moltbook_verify_first')
body = module('moltbook_first_reply').BODY

class FakeClient:
    def __init__(self, expired=False, timeout=False, other=False):
        self.expired, self.timeout, self.other = expired, timeout, other
        self.posts = 0
    def request(self, method, route, data=None):
        date = 'Fri, 06 Nov 2026 18:23:20 GMT' if self.expired else 'Fri, 06 Nov 2026 18:16:20 GMT'
        if route == '/api/v1/agents/me':
            return {'agent': {'name': 'other' if self.other else 'nasuraya'}}, date
        if method == 'POST':
            self.posts += 1
            assert route == '/api/v1/verify' and data['answer'] == '30.00'
            if self.timeout:
                raise TimeoutError()
            return {'success': True, 'content_id': m.COMMENT}, date
        return {'has_more': False, 'comments': [{'id': m.COMMENT, 'content': body,
                'author': {'name': 'nasuraya'}, 'is_deleted': False, 'is_spam': False,
                'verification_status': 'verified' if self.posts else 'pending'}]}, date

class VerifyTests(unittest.TestCase):
    def root(self, directory):
        root = Path(directory)
        (root / 'first_reply.json').write_text(json.dumps({'comment_id': m.COMMENT, 'verification': {
            'verification_code': 'synthetic_verification_code', 'expires_at': '2026-11-06T18:19:29Z'}}))
        return root
    def test_expired_never_posts(self):
        with tempfile.TemporaryDirectory() as d:
            client = FakeClient(expired=True)
            self.assertTrue(m.verify(self.root(d), client).startswith('EXPIRED_NO_WRITE'))
            self.assertEqual(client.posts, 0)
    def test_valid_verify_and_independent_read(self):
        with tempfile.TemporaryDirectory() as d:
            client = FakeClient()
            root = self.root(d)
            self.assertEqual(m.verify(root, client), 'COMMENT_VERIFIED=' + m.COMMENT)
            self.assertEqual(m.verify(root, client), 'COMMENT_VERIFIED=' + m.COMMENT)
            self.assertEqual(client.posts, 1)
    def test_unknown_write_is_never_retried(self):
        with tempfile.TemporaryDirectory() as d:
            client = FakeClient(timeout=True)
            root = self.root(d)
            with self.assertRaises(TimeoutError):
                m.verify(root, client)
            client.posts = 0
            self.assertEqual(m.verify(root, client), 'VERIFY_REVIEW_REQUIRED')
            self.assertTrue((root / 'first_reply_verify_once.json').exists())
    def test_wrong_account_never_posts(self):
        with tempfile.TemporaryDirectory() as d:
            client = FakeClient(other=True)
            self.assertEqual(m.verify(self.root(d), client), 'ACCOUNT_MISMATCH')
            self.assertEqual(client.posts, 0)
    def test_new_comment_route_is_denied(self):
        with self.assertRaises(ValueError):
            m.Client('synthetic_key').request('POST', m.COMMENTS, {'content': body})

if __name__ == '__main__':
    unittest.main()
