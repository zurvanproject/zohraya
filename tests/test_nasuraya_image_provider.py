"""Fully offline contract tests for opt-in GPT Image adapter (no API keys)."""
import base64
from hashlib import sha256
import json
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
import unittest
from urllib.error import HTTPError
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import nasuraya_image_provider as provider


def png_chunk(ctype: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(ctype + data) & 0xffffffff
    return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", checksum)


def valid_png() -> bytes:
    """Real tiny compressed 256x256 RGBA PNG; fully offline and deterministic."""
    width, height = 256, 256
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    pixel_row = b"\x00" + b"\x23\x42\x55\xff" * width
    image = zlib.compress(pixel_row * height)
    return signature + png_chunk(b"IHDR", ihdr) + png_chunk(b"IDAT", image) + png_chunk(b"IEND", b"")


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self, maximum: int) -> bytes:
        return self.payload[:maximum]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class ProviderTests(unittest.TestCase):
    def test_plan_is_one_explicit_image(self):
        p = provider.plan()
        self.assertEqual(p["n"], 1)
        self.assertEqual(p["model"], "gpt-image-2.5-flare")
        self.assertEqual(p["output_format"], "png")
        self.assertEqual(p["quality"], "low")
        self.assertIn("BLANK cream paper", p["prompt"])
        with self.assertRaises(ValueError):
            provider.plan(model="gpt-image-1")
        with self.assertRaises(ValueError):
            provider.plan(scene="unrecognized")

    def test_no_key_no_request(self):
        called = []
        def cannot_run(*args, **kwargs):
            called.append(1)
            raise RuntimeError("must never execute")
        with self.assertRaisesRegex(provider.ImageProviderError, "OPENAI_API_KEY"):
            provider.request_image(provider.plan(), "", transport=cannot_run)
        self.assertEqual(called, [])

    def test_one_mock_request_with_true_provenance(self):
        image_bytes = valid_png()
        body = json.dumps({
            "data": [{"b64_json": base64.b64encode(image_bytes).decode("ascii")}]
        }).encode("utf-8")
        sent = []
        def fake_transport(request, *, timeout):
            sent.append((request, timeout))
            return FakeResponse(body)
        with TemporaryDirectory() as tmp:
            receipt = provider.execute(Path(tmp) / "run", "observatory",
                                       "gpt-image-2.5-flare", "low",
                                       "secret-NEVER-SAVE", transport=fake_transport)
            self.assertEqual(len(sent), 1)
            request, timeout = sent[0]
            self.assertEqual(request.full_url, provider.API_ENDPOINT)
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(timeout, 180)
            self.assertEqual(json.loads(request.data)["n"], 1)
            self.assertTrue(receipt["image_model_invoked"])
            self.assertTrue(receipt["api_request_completed"])
            self.assertFalse(receipt["published"])
            self.assertFalse(receipt["server_executed"])
            path = Path(tmp) / "run"
            self.assertEqual((path / "gallery/nasuraya.png").read_bytes(), image_bytes)
            manifest = json.loads((path / "gallery/manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["method"], "api-generated-pending-review")
            self.assertTrue(manifest["image_model_invoked"])
            self.assertFalse(manifest["quality_checks"]["visual_anatomy_reviewed"])
            self.assertEqual(manifest["portrait_sha256"], sha256(image_bytes).hexdigest())
            self.assertIn("class=\"on-paper\"", (path / "gallery/index.html").read_text(encoding="utf-8"))
            files_joined = (path / "api-generation-receipt.json").read_text(encoding="utf-8")
            self.assertNotIn("secret-NEVER-SAVE", files_joined)
            self.assertEqual(len(list(path.glob("nasuraya-*.png"))), 0)

    def test_error_redacts_provider_body(self):
        def fake_http_error(request, *, timeout):
            raise HTTPError(provider.API_ENDPOINT, 403, "SECRET-IN-PROVIDER-BODY", {}, None)
        with self.assertRaises(provider.ImageProviderError) as ctx:
            provider.request_image(provider.plan(), "top-secret-key", fake_http_error)
        self.assertIn("403", str(ctx.exception))
        self.assertNotIn("SECRET", str(ctx.exception))
        self.assertNotIn("top-secret-key", str(ctx.exception))

    def test_malformed_image_rejected_without_gallery(self):
        fake_data = b"\x89PNG\r\n\x1a\n" + b"wrong payload"
        body = json.dumps({"data": [{"b64_json": base64.b64encode(fake_data).decode()}]}).encode()
        def fake_transport(*args, **kwargs):
            return FakeResponse(body)
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "no-output"
            with self.assertRaises(provider.ImageProviderError):
                provider.execute(out, "library", "gpt-image-2.5-flare",
                                 "low", "fake-key", transport=fake_transport)
            self.assertFalse(out.exists())

    def test_base64_contract_and_dimension_bounds(self):
        self.assertEqual(provider.inspect_png(valid_png()), (256, 256))
        with self.assertRaises(provider.ImageProviderError):
            provider.inspect_png(b"bad")
        body = b'{"data":[{"b64_json":"invalid??"}]}'
        with self.assertRaises(provider.ImageProviderError):
            provider.request_image(provider.plan(), "fake", lambda *a, **k: FakeResponse(body))


if __name__ == "__main__":
    unittest.main()
