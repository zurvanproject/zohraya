"""Real Linux readout; Windows verifies the saved bounded export offline."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from examples.dios_nous.unified import body, native_readout

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get("DIOS_NATIVE_SOURCE_ROOT", str(ROOT)))
EVIDENCE = ROOT / "docs/evidence/dios-unified-20261112/native-readout.json"
AVAILABLE = all((SOURCE / p).is_file() for p in native_readout.SOURCE_BLOBS)


class NativeReadoutTests(unittest.TestCase):
    def test_windows_entrypoint_explicitly_requires_export(self):
        with patch.object(native_readout.sys, "platform", "win32"), patch.object(native_readout.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "Windows uses exported JSON"):
                native_readout.run_readout(SOURCE)
            run.assert_not_called()

    def test_existing_cli_output_rejected_before_any_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "receipt.json"
            target.write_text("preserve", encoding="utf-8")
            for option in ("--output", "--export-output"):
                with patch.object(sys, "argv", ["native_readout", option, str(target)]), patch.object(native_readout, "execute_native_readout") as run:
                    with self.assertRaises(SystemExit):
                        native_readout.main()
                    run.assert_not_called()
                self.assertEqual(target.read_text(encoding="utf-8"), "preserve")

    def test_saved_real_readout_export_remains_verifiable_cross_platform(self):
        saved = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        export = saved["native_export"]
        result = body.normalize_native(export, now_s=0)
        self.assertEqual(result, saved["normalized"])
        self.assertEqual(saved["before_checkpoint_sha256"], saved["after_checkpoint_sha256"])
        self.assertTrue(saved["before_after_equal"])
        self.assertEqual(saved["native_cycles_executed"], 0)
        self.assertEqual(saved["action_requests_executed"], 0)
        self.assertEqual(saved["model_api_calls"], 0)
        self.assertEqual(saved["forbidden_dynamic_calls"], 0)
        self.assertFalse(result["source_authenticated"])
        self.assertIn("fresh_initial_state_not_live_saved_user_body", saved["limitations"])

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux native runtime; Windows consumes exports")
    def test_source_mismatch_is_rejected_before_starting_subprocess(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = next(iter(native_readout.SOURCE_BLOBS))
            target = root / first
            target.parent.mkdir(parents=True)
            target.write_text("tampered", encoding="utf-8")
            with patch.object(native_readout.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "source hash mismatch"):
                    native_readout.run_readout(root)
                run.assert_not_called()

    @unittest.skipUnless(sys.platform.startswith("linux") and AVAILABLE,
                         "Needs Linux and pinned native sources; set DIOS_NATIVE_SOURCE_ROOT if sparse")
    def test_direct_worker_cannot_overwrite_caller_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative, raw in native_readout._sources(SOURCE).items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            canaries = []
            for name in ("trained_circuit.json", "initial_affect.json"):
                path = root / "runtimes/tadash_body/retained_extensions" / name
                path.write_text("private canary; must not read or overwrite", encoding="utf-8")
                canaries.append(path)
            run = subprocess.run([sys.executable, "-I", "-S", native_readout.__file__,
                                  "--worker", str(root)], capture_output=True, text=True,
                                 encoding="utf-8", timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertNotIn("private canary", run.stdout)
            for path in canaries:
                self.assertEqual(path.read_text(encoding="utf-8"), "private canary; must not read or overwrite")
            self.assertTrue(json.loads(run.stdout)["before_after_equal"])

    @unittest.skipUnless(sys.platform.startswith("linux") and AVAILABLE,
                         "Needs Linux and pinned native sources; set DIOS_NATIVE_SOURCE_ROOT if sparse")
    def test_actual_native_initial_state_readout_in_fresh_process(self):
        expected_sources = native_readout._sources(SOURCE)
        result = native_readout.run_readout(SOURCE)
        self.assertEqual(native_readout._sources(SOURCE), expected_sources)
        self.assertTrue(result["before_after_equal"])
        self.assertEqual(result["simulated_time_s"], 0)
        self.assertEqual(result["revision"], 0)
        self.assertEqual(result["forbidden_dynamic_calls"], 0)
        self.assertEqual(result["guarded_dynamic_entrypoints"], 10)
        self.assertEqual(len(result["source_files"]), 45)
        self.assertEqual(set(result["native_export"]["minimum_state"]), set(body.MINIMUM))
        self.assertEqual(set(result["native_export"]["finite_stocks"]), set(body.STOCKS))
        self.assertEqual(result["research_observer"]["sensory"]["q"], [1., 1., 0., 0., .35, 1.])
        self.assertEqual(result["normalized"]["minimum_state"]["posture"]["value"], "double_support")
        self.assertFalse(result["normalized"]["physical_sensor_connected"])
        saved = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        # Cross-Python sum rounding changes two proprioceptive loads outside this
        # export. Broad body/checkpoint hashes remain integrity checks per run,
        # not cross-runtime bit-identity criteria; see the recorded CI diagnosis.
        self.assertEqual(result["runtime_python_version"], sys.version.split()[0])
        self.assertEqual(result["observation"]["source_identity"], saved["observation"]["source_identity"])
        self.assertEqual(result["native_export"]["minimum_state"], saved["native_export"]["minimum_state"])
        self.assertEqual(result["native_export"]["finite_stocks"], saved["native_export"]["finite_stocks"])


if __name__ == "__main__":
    unittest.main()
