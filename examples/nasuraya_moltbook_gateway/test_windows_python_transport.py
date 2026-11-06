"""Offline checks for the Python HTTPS code embedded in the Windows bridge."""
import contextlib
import io
import json
from pathlib import Path
import re
import ssl
import types
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request


SOURCE = re.search(r"\$script:PythonReadOnly = @'\n(.*?)\n'@",
    Path(__file__).with_name('windows_moltbook.ps1').read_text(encoding='utf-8'), re.S).group(1)
MOD = types.ModuleType('windows_python_transport')
exec(compile(SOURCE, 'windows_python_transport', 'exec'), MOD.__dict__)
KEY = 'SYNTHETIC_KEY_NOT_A_REAL_CREDENTIAL'
ROUTE = '/api/v1/agents/status'


class TransportTests(unittest.TestCase):
    def run_request(self, payload, *, status=200):
        response = Mock(status=status)
        response.read.return_value = payload
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with patch.dict('sys.modules', {'certifi': types.SimpleNamespace(where=lambda: 'roots.pem')}), \
             patch.object(MOD.ssl, 'create_default_context', return_value=context) as tls, \
             patch.object(MOD.urllib.request, 'build_opener', return_value=opener) as build:
            result = MOD.read_api(ROUTE, KEY)
        tls.assert_called_once_with(cafile='roots.pem')
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        handlers = build.call_args.args
        self.assertEqual(handlers[0].proxies, {})
        self.assertIsInstance(handlers[1], MOD.NoRedirect)
        req = opener.open.call_args.args[0]
        self.assertEqual(req.full_url, 'https://www.moltbook.com' + ROUTE)
        self.assertEqual(req.get_method(), 'GET')
        self.assertEqual(req.headers['Authorization'], 'Bearer ' + KEY)
        self.assertIsNone(req.data)
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 15)
        response.read.assert_called_once_with(MOD.MAX_BODY + 1)
        return result

    def test_verified_fixed_get_and_bounded_read(self):
        self.assertEqual(self.run_request(b'{"status":"claimed"}'), {'status': 'claimed'})

    def test_bad_routes_rejected_before_network(self):
        for route in ['https://evil.example', '/api/v1/posts', '/api/v1/agents/me\r\nX: bad', '/api/v1/posts?sort=new&limit=100']:
            with self.subTest(route=route), self.assertRaises(ValueError):
                MOD.read_api(route, KEY)

    def test_bad_keys_rejected(self):
        for key in ['', 'bad key', 'a' * 257, KEY + '\r\nX: bad']:
            with self.subTest(key_length=len(key)), self.assertRaises(ValueError):
                MOD.read_api(ROUTE, key)

    def test_redirects_are_not_followed(self):
        handler = MOD.NoRedirect()
        req = urllib.request.Request('https://www.moltbook.com' + ROUTE)
        for code in [301, 302, 303, 307, 308]:
            self.assertIsNone(handler.redirect_request(req, None, code, '', {}, 'https://evil.example'))

    def test_large_and_malformed_responses_rejected(self):
        for data in [b'x' * (MOD.MAX_BODY + 1), b'[]', b'{"v":NaN}', b'not json', b'\xff']:
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                self.run_request(data)

    def test_non_200_rejected(self):
        with self.assertRaises(ValueError):
            self.run_request(b'{}', status=201)

    def test_failure_diagnostics_do_not_echo_secrets(self):
        failures = [
            (urllib.error.HTTPError('https://www.moltbook.com', 401, KEY, {}, None), 401, 'TransportFailure'),
            (urllib.error.URLError(ssl.SSLCertVerificationError(1, KEY)), None, 'CertificateFailure'),
            (urllib.error.URLError(TimeoutError(KEY)), None, 'Timeout'),
            (ImportError(KEY), None, 'MissingDependency'),
            (ValueError(KEY), None, 'InvalidData'),
        ]
        for exc, status, kind in failures:
            out = io.StringIO()
            with patch.object(MOD.sys, 'argv', ['bridge', ROUTE]), \
                 patch.object(MOD.sys, 'stdin', types.SimpleNamespace(buffer=io.BytesIO(KEY.encode()))), \
                 patch.object(MOD, 'read_api', side_effect=exc), contextlib.redirect_stdout(out):
                self.assertEqual(MOD.main(), 1)
            self.assertNotIn(KEY, out.getvalue())
            self.assertEqual(json.loads(out.getvalue()),
                {'ok': False, 'http_status': status, 'network_status': kind})

    def test_success_envelope(self):
        out = io.StringIO()
        with patch.object(MOD.sys, 'argv', ['bridge', ROUTE]), \
             patch.object(MOD.sys, 'stdin', types.SimpleNamespace(buffer=io.BytesIO(KEY.encode() + b'\r\n'))), \
             patch.object(MOD, 'read_api', return_value={'status': 'claimed'}) as call, \
             contextlib.redirect_stdout(out):
            self.assertEqual(MOD.main(), 0)
        call.assert_called_once_with(ROUTE, KEY)
        self.assertEqual(json.loads(out.getvalue()), {'ok': True, 'data': {'status': 'claimed'}})

    def test_dotnet_utf8_bom_on_stdin(self):
        out = io.StringIO()
        with patch.object(MOD.sys, 'argv', ['bridge', ROUTE]), \
             patch.object(MOD.sys, 'stdin', types.SimpleNamespace(buffer=io.BytesIO(b'\xef\xbb\xbf' + KEY.encode() + b'\r\n'))), \
             patch.object(MOD, 'read_api', return_value={}) as call, contextlib.redirect_stdout(out):
            self.assertEqual(MOD.main(), 0)
        call.assert_called_once_with(ROUTE, KEY)


if __name__ == '__main__':
    unittest.main()
