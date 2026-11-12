"""Integration/serialization checks for pinned reduced models, not efficacy tests."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback
import unittest
from unittest.mock import patch

from examples.dios_nous.unified import state_models


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def numeric_leaves(value):
    if type(value) in (int, float):
        return 1
    if isinstance(value, dict):
        return sum(numeric_leaves(child) for child in value.values())
    if isinstance(value, list):
        return sum(numeric_leaves(child) for child in value)
    return 0


class NativeStateModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="private-native-path-canary-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.modules_before = set(sys.modules)
        cls.result = state_models.run_models(cls.root)
        cls.modules_after = set(sys.modules)

    def test_neural_native_checkpoint_and_continuation_preserve_complete_state(self):
        neural = self.result["models"]["neural"]
        self.assertTrue(neural["checkpoint_roundtrip_equal"])
        self.assertTrue(neural["continuation_equal"])
        self.assertEqual(neural["counts"]["cells"], 6)
        self.assertEqual(neural["counts"]["synapses"], 9)
        self.assertEqual(neural["state"]["tick"], 128)
        self.assertGreater(neural["state"]["neurons"]["arm_input"]["spike_count"], 0)
        self.assertEqual(neural["state"]["neurons"]["seat_input"]["spike_count"], 0)
        saved = json.loads((self.root / "neural.json").read_bytes())
        self.assertEqual(saved["payload"], neural["state"])
        self.assertEqual(neural["units"]["voltage_mv"], "mV")
        self.assertFalse(neural["llm_weights_accessed"])

    def test_affect_runs_neutral_transition_and_native_persistence(self):
        affect = self.result["models"]["affect"]
        self.assertTrue(affect["checkpoint_roundtrip_equal"])
        self.assertNotEqual(affect["initial_state"]["affect"], affect["state"]["affect"])
        self.assertEqual(affect["counts"]["affect_channels"], 44)
        self.assertEqual(affect["counts"]["somatic_channels"], 10)
        self.assertEqual(affect["counts"]["goal_weights"], 5)
        self.assertEqual(affect["state"]["relationships"], {})
        self.assertEqual(affect["plan_disposition"], "plan_only")
        self.assertFalse(affect["subjective_feeling_claim"])
        self.assertFalse(affect["external_message_sent"])
        self.assertNotIn("partner", affect["fixture"])
        self.assertNotIn("summary", affect["fixture"])
        self.assertNotIn("relationship_mode", affect["fixture"])
        self.assertEqual(set(affect["fixture"]["signals"]),
                         {"novelty", "uncertainty", "blocked_goal", "value_goal", "possibility"})
        saved = json.loads((self.root / "affect.json").read_bytes())
        saved.pop("integrity")
        self.assertEqual(saved, affect["state"])
        self.assertEqual(affect["state"]["claim_scope"], "engineering_state_only")

    def test_genome_uses_native_contract_validation_without_mutation_or_apply(self):
        genome = self.result["models"]["genome"]
        self.assertEqual(genome["counts"]["chromosomes"], 48)
        self.assertEqual(genome["counts"]["pairs"], 24)
        self.assertEqual(genome["counts"]["loci"], 28)
        self.assertEqual(genome["counts"]["alleles"], 56)
        self.assertEqual(genome["state"]["revision"], 0)
        self.assertIsNone(genome["state"]["parent_sha256"])
        self.assertTrue(genome["contract_source_comparison_equal"])
        self.assertTrue(genome["checkpoint_roundtrip_equal"])
        self.assertFalse(genome["native_apply_allowed"])
        self.assertFalse(genome["native_body_advanced"])
        self.assertFalse(genome["mutation_performed"])
        self.assertFalse(genome["proposal"]["compatibility"]["structural_changed"])
        self.assertFalse(genome["proposal"]["compatibility"]["copy_deviation"])
        self.assertEqual(genome["proposal"]["simulated_physiology_proxy"]["payload"]["modules"]["G12"]["development_capacity"], 0)
        saved = json.loads((self.root / "genome.json").read_bytes())
        self.assertEqual(saved["payload"]["genotype"], genome["state"])

    def test_source_pins_and_checkpoint_digests_identify_actual_bytes(self):
        pins, sources = state_models._sources()
        self.assertEqual(len(pins), 10)
        self.assertEqual(pins["examples/nasuraya_genome/traits.py"]["git_blob_sha1"],
                         "3210475167020d4ce42c39eff60898da20bcf9fb")
        for name, model in self.result["models"].items():
            self.assertEqual(hashlib.sha256((self.root / (name + ".json")).read_bytes()).hexdigest(),
                             model["checkpoint_sha256"])
            self.assertEqual(hashlib.sha256(canonical(model["state"])).hexdigest(), model["state_sha256"])
            for source in model["source_pins"]:
                raw = sources[source["path"]]
                self.assertEqual(hashlib.sha256(raw).hexdigest(), source["sha256"])
        self.assertTrue(self.result["source_bytes_unchanged"])

    def test_reported_counts_cover_the_serialized_parameter_states(self):
        for model in self.result["models"].values():
            self.assertEqual(model["counts"]["state_numeric_leaves"], numeric_leaves(model["state"]))
        affect = self.result["models"]["affect"]
        self.assertEqual(affect["counts"]["parameter_numeric_leaves"], numeric_leaves(affect["parameters"]))
        neural = self.result["models"]["neural"]
        self.assertEqual(neural["counts"]["parameter_numeric_leaves"], numeric_leaves(
            {key: neural["state"][key] for key in ("dt_ms", "cells", "synapses")}))

    def test_finite_report_does_not_promote_states_to_truth_or_authority(self):
        result = dict(self.result)
        digest = result.pop("result_sha256")
        raw = canonical(result)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
        self.assertNotIn(b"private-native-path-canary-", raw)
        self.assertIsNone(result["confidence"])
        self.assertEqual(result["calibration"], "not_measured")
        self.assertFalse(result["execution_permitted"])
        self.assertEqual(result["external_actions_taken"], 0)
        self.assertEqual(result["network_calls"], 0)
        self.assertEqual(result["model_api_calls"], 0)
        self.assertEqual(result["runtime_utf8_mode"], 1)
        self.assertEqual(result["models"]["affect"]["units"]["confidence"],
                         "authored_appraisal_multiplier_not_epistemic_confidence")

    def test_legacy_imports_do_not_pollute_parent_process(self):
        added = self.modules_after - self.modules_before
        for name in ("neural_circuit", "nasuraya_affective_layer_v01",
                     "nasuraya_decision_core_v1", "nasuraya_emotion_spectrum_v01",
                     "examples.nasuraya_genome.traits", "examples.nasuraya_genome.chromosomes"):
            self.assertNotIn(name, added)

    def test_nonempty_output_is_rejected_without_overwriting_checkpoints(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        with self.assertRaisesRegex(ValueError, "require_empty_directory"):
            state_models.run_models(self.root)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_changed_source_is_rejected_before_any_legacy_import_or_checkpoint(self):
        with tempfile.TemporaryDirectory() as name:
            temporary = Path(name)
            altered = temporary / "sources"
            shutil.copytree(state_models.STATE_SOURCE_ROOT, altered)
            target = altered / "runtimes/tadash_body/retained_extensions/nasuraya_decision_core_v1.py"
            target.write_bytes(target.read_bytes() + b"\nraise RuntimeError('must not execute')\n")
            output = temporary / "output"
            with patch.object(state_models, "STATE_SOURCE_ROOT", altered), patch.object(state_models.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "source bytes changed"):
                    state_models.run_models(output)
                run.assert_not_called()
            self.assertFalse(output.exists())

    def test_worker_writes_utf8_bytes_when_redirected_text_stream_is_ascii(self):
        # Emulate a narrow Windows stdout codec inside the real isolated worker.
        # This test failed with UnicodeEncodeError when output used text print().
        worker = state_models._WORKER.replace(
            "sys.dont_write_bytecode = True",
            "sys.stdout.reconfigure(encoding='ascii', errors='strict')\n"
            "sys.dont_write_bytecode = True", 1)
        self.assertNotEqual(worker, state_models._WORKER)
        with tempfile.TemporaryDirectory() as name, patch.object(state_models, "_WORKER", worker):
            result = state_models.run_models(Path(name))
        self.assertEqual(result["models"]["affect"]["parameters"]["profiles"]["love"][0], "دوست داشتن")
        self.assertTrue(all(model["checkpoint_roundtrip_equal"] for model in result["models"].values()))
        canonical(result)

    def test_worker_explicit_utf8_mode_covers_legacy_default_file_reads(self):
        # Emulate Windows' default file codec while respecting explicit UTF-8
        # mode. Omitting -X utf8 must fail even on a UTF-8 Linux host.
        injection = """_real_read_text = Path.read_text
def _windows_default_read_text(self, *args, **kwargs):
    if not args and kwargs.get('encoding') is None:
        kwargs['encoding'] = 'utf-8' if sys.flags.utf8_mode else 'cp1252'
    return _real_read_text(self, *args, **kwargs)
Path.read_text = _windows_default_read_text
"""
        worker = state_models._WORKER.replace(
            "sys.dont_write_bytecode = True", injection + "\nsys.dont_write_bytecode = True", 1)
        self.assertNotEqual(worker, state_models._WORKER)
        with tempfile.TemporaryDirectory() as name, patch.object(state_models, "_WORKER", worker):
            result = state_models.run_models(Path(name))
        self.assertEqual(result["runtime_utf8_mode"], 1)
        self.assertTrue(result["models"]["genome"]["contract_source_comparison_equal"])
        self.assertEqual(result["models"]["genome"]["counts"]["chromosomes"], 48)

    def test_worker_failure_reports_only_code_and_stderr_digest(self):
        secret = b"PRIVATE_ERROR_CANARY\xff/private/output/path"
        completed = subprocess.CompletedProcess(["PRIVATE_SCRIPT_CANARY"], 7, b"", secret)
        with tempfile.TemporaryDirectory() as name, patch.object(state_models.subprocess, "run", return_value=completed):
            with self.assertRaises(RuntimeError) as caught:
                state_models.run_models(Path(name))
        self.assertEqual(str(caught.exception), "native_state_worker_failed;returncode=7;stderr_sha256="
                         + hashlib.sha256(secret).hexdigest())
        self.assertNotIn("PRIVATE", "".join(traceback.format_exception(caught.exception)))

    def test_worker_timeout_does_not_expose_script_paths_or_stderr(self):
        secret = b"PRIVATE_TIMEOUT_CANARY/private/output/path"
        failure = subprocess.TimeoutExpired(["PRIVATE_SCRIPT_CANARY"], 30, stderr=secret)
        with tempfile.TemporaryDirectory() as name, patch.object(state_models.subprocess, "run", side_effect=failure):
            with self.assertRaises(RuntimeError) as caught:
                state_models.run_models(Path(name))
        self.assertEqual(str(caught.exception), "native_state_worker_timed_out;stderr_sha256="
                         + hashlib.sha256(secret).hexdigest())
        self.assertNotIn("PRIVATE", "".join(traceback.format_exception(caught.exception)))

    def test_worker_launch_failure_hides_private_path(self):
        failure = OSError(2, "PRIVATE_LAUNCH_CANARY", "/private/output/path")
        with tempfile.TemporaryDirectory() as name, patch.object(state_models.subprocess, "run", side_effect=failure):
            with self.assertRaises(RuntimeError) as caught:
                state_models.run_models(Path(name))
        self.assertEqual(str(caught.exception), "native_state_worker_launch_failed;errno=2")
        self.assertNotIn("PRIVATE", "".join(traceback.format_exception(caught.exception)))

    def test_malformed_worker_output_is_hashed_without_echoing_bytes(self):
        secret = b"PRIVATE_OUTPUT_CANARY\xff/private/output/path"
        completed = subprocess.CompletedProcess(["PRIVATE_SCRIPT_CANARY"], 0, secret, b"")
        with tempfile.TemporaryDirectory() as name, patch.object(state_models.subprocess, "run", return_value=completed):
            with self.assertRaises(RuntimeError) as caught:
                state_models.run_models(Path(name))
        self.assertEqual(str(caught.exception), "native_state_worker_invalid_json;stdout_sha256="
                         + hashlib.sha256(secret).hexdigest())
        self.assertNotIn("PRIVATE", "".join(traceback.format_exception(caught.exception)))


if __name__ == "__main__":
    unittest.main()
