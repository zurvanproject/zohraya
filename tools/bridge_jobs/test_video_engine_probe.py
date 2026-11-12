"""Check refusal, bounded scans and a real pipe encode/decode locally."""
import hashlib
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "probe", Path(__file__).with_name("nasu_video_engine_probe.py"))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def test_unverified_binary_is_never_executed(self):
        with tempfile.TemporaryDirectory() as temporary:
            exe = Path(temporary) / "ffmpeg.exe"
            exe.write_bytes(b"not the approved executable")
            with patch.object(probe.subprocess, "run") as run:
                self.assertEqual(probe.encode_decode(exe), "HASH_FAIL")
                run.assert_not_called()

    def test_scan_limit_is_not_reported_as_absence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for i in range(5):
                (root / f"example{i}.txt").touch()
            self.assertEqual(probe.scan_models([root], max_entries=1)[2], "PARTIAL")

    def test_weights_detected_without_reading_contents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (root / "model.safetensors").open("wb") as stream:
                stream.truncate(9 * 1024 * 1024)
            with patch.object(Path, "read_bytes", side_effect=AssertionError("no contents")):
                self.assertEqual(probe.scan_models([root]), (1, 0, "OK"))

    def test_no_torch_does_not_launch_child(self):
        with patch.object(probe.subprocess, "run") as run:
            self.assertEqual(probe.torch_runtime(0), "NO_TORCH")
            run.assert_not_called()

    def test_public_output_rejects_paths(self):
        self.assertEqual(probe.summary({"BAD": r"C:\Users\private"}), "AUDIT=OUTPUT_REJECTED")

    @unittest.skipUnless(shutil.which("ffmpeg"), "local FFmpeg not installed")
    def test_actual_pipe_encode_decode(self):
        exe = Path(shutil.which("ffmpeg")).resolve()
        raw = exe.read_bytes()
        with patch.object(probe, "EXE_BYTES", len(raw)), patch.object(probe, "EXE_SHA", hashlib.sha256(raw).hexdigest()):
            self.assertEqual(probe.encode_decode(exe), "ENC_DEC_OK")


if __name__ == "__main__":
    unittest.main()
