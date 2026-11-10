"""Offline integrity tests. Windows CI separately exercises the real installer."""
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('installer', Path(__file__).with_name('nasu_video241_install.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class InstallTests(unittest.TestCase):
    def test_unsupported_platform_does_not_download_or_mutate(self):
        with patch.object(m.platform, 'system', return_value='Linux'), patch.object(m, 'download') as fetch:
            self.assertIn('SKIPPED', m.install()['summary'])
            fetch.assert_not_called()

    def test_corrupt_wheel_rejected_before_zip_open(self):
        with patch.object(m.zipfile, 'ZipFile') as archive, self.assertRaises(ValueError):
            m.extract_verified(b'bad')
        archive.assert_not_called()

    def test_tampered_download_rejected(self):
        with self.assertRaises(ValueError):
            m.download(lambda *_args, **_kwargs: io.BytesIO(b'bad download'))

    def test_oversized_download_rejected(self):
        with patch.object(m, 'WHEEL_BYTES', 4), self.assertRaises(ValueError):
            m.download(lambda *_args, **_kwargs: io.BytesIO(b'oversize'))

    def test_deadline_enforced(self):
        with patch.object(m.time, 'monotonic', side_effect=[0, 100]), self.assertRaises(TimeoutError):
            m.download(lambda *_args, **_kwargs: io.BytesIO(b''))

    def test_valid_existing_binary_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'ffmpeg.exe').write_bytes(b'checked')
            with patch.object(m, 'EXE_BYTES', 7), patch.object(m, 'EXE_SHA256', m.digest(b'checked')):
                self.assertEqual(m.ensure_binary(root, lambda: self.fail('must not fetch')), root / 'ffmpeg.exe')

    def test_invalid_existing_binary_is_not_replaced_on_bad_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'ffmpeg.exe').write_bytes(b'old')
            with self.assertRaises(ValueError):
                m.ensure_binary(root, lambda: b'bad')
            self.assertEqual((root / 'ffmpeg.exe').read_bytes(), b'old')

    def test_atomic_write_completes_without_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'receipt.json'
            m.atomic_write(path, b'{}')
            self.assertEqual(path.read_bytes(), b'{}')
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)


if __name__ == '__main__':
    unittest.main()
