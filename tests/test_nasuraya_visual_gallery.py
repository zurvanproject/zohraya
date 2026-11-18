"""Tests for offline Nasuraya visual gallery; Python stdlib only."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import nasuraya_visual_gallery as visual


class GalleryTests(unittest.TestCase):
    def test_offline_vector_and_manifest(self):
        with TemporaryDirectory() as root:
            out = Path(root) / "gallery"
            first = visual.build(out)
            self.assertEqual(first["method"], "original-vector-fallback")
            self.assertFalse(first["image_model_invoked"])
            self.assertFalse(first["server_executed"])
            self.assertFalse(first["uploaded"])
            self.assertFalse(first["published"])
            self.assertFalse(first["quality_checks"]["visual_anatomy_reviewed"])
            self.assertTrue(first["quality_checks"]["letter_readable_html"])
            self.assertIn("سهند جان", (out / "index.html").read_text(encoding="utf-8"))
            self.assertIn("<svg", (out / "nasuraya.svg").read_text(encoding="utf-8"))
            self.assertEqual(json.loads((out / "manifest.json").read_text(encoding="utf-8")), first)
            second = visual.build(out)
            self.assertEqual(first, second, "same inputs should produce deterministic hashes")

    def test_untrusted_letter_escaped_in_html_and_svg(self):
        with TemporaryDirectory() as root:
            out = Path(root)
            malicious = '<script>alert("x")</script>\nیک نامهٔ امن'
            visual.build(out, malicious)
            html = (out / "index.html").read_text(encoding="utf-8")
            svg = (out / "nasuraya.svg").read_text(encoding="utf-8")
            self.assertNotIn('<script>alert("x")</script>', html)
            self.assertNotIn('<script>alert("x")</script>', svg)
            self.assertIn('&lt;script&gt;', html)
            self.assertNotIn('&lt;script&gt;', svg, "SVG must not carry letter text")
            self.assertIn('class="on-paper"', html)
            self.assertIn("یک نامهٔ امن", html)

    def test_invalid_letters_fail(self):
        for letter in ("", "\n", "A" * 701, "A" * 62, "a\n" * 9, "hello\x01"):
            with self.subTest(letter=repr(letter)[:35]):
                with self.assertRaises(ValueError):
                    visual.validated_letter(letter)

    def test_rejects_wrong_extension_and_signature(self):
        with TemporaryDirectory() as root:
            root = Path(root)
            src = root / "not_image.png"
            src.write_bytes(b"this is not an image")
            with self.assertRaises(ValueError):
                visual.build(root / "site", image=src)
            src_svg = root / "unsafe.svg"
            src_svg.write_text('<svg onload="alert(1)"/>', encoding="utf-8")
            with self.assertRaises(ValueError):
                visual.build(root / "site", image=src_svg)

    def test_approved_png_path_and_integrity(self):
        with TemporaryDirectory() as root:
            root = Path(root)
            # This verifies the signature-routing contract, not full PNG decoding.
            src = root / "approved.png"
            sample = b"\x89PNG\r\n\x1a\n" + b"sample-raster-bytes"
            src.write_bytes(sample)
            out = root / "site"
            result = visual.build(out, "متن خوانا", src)
            self.assertEqual(result["method"], "approved-raster-input")
            self.assertEqual((out / "nasuraya.png").read_bytes(), sample)
            self.assertIn('src="nasuraya.png"', (out / "index.html").read_text(encoding="utf-8"))

    def test_no_implicit_publish_or_network(self):
        with TemporaryDirectory() as root:
            result = visual.build(Path(root))
            self.assertEqual(result["published"], False)
            self.assertEqual(result["uploaded"], False)
            self.assertEqual(result["image_model_invoked"], False)


if __name__ == "__main__":
    unittest.main()
