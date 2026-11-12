"""Pinned native readout in a disposable Linux subprocess, without body cycles.

This creates a fresh authored simulation at time zero. It never loads a user
checkpoint, steps physiology, calls models, connects sensors or requests actions.
Windows consumes the closed export through body.normalize_native instead.
Source files must already be present locally; this module performs no download.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

SOURCE_COMMIT = "a532f24a5b3eb7a31df6d200950c7287e1e96a35"
SOURCE_BLOBS = {
    "runtimes/tadash_body/IMPORT_PROVENANCE.json": "86a34318bc8556c5bd849fdd0d3ab126a147ffd6",
    "runtimes/tadash_body/PUBLIC_FILES_SHA256.json": "98dd4cbd32fa97f6a61505c48a02a25b92833fdf",
    "runtimes/tadash_body/RECOVERED_FILES_SHA256.json": "1d4afe7247e2d3f14a1a257eec2d8d0a2df78495",
    "runtimes/tadash_body/REFLECTION_PROVENANCE.json": "bae7356c22f9b22f9d7a836f52be43fbd539ac2c",
    "runtimes/tadash_body/SOURCE_PROVENANCE.json": "666a2199fd1bb1f42a21aaf982800eccf55bcf47",
    "runtimes/tadash_body/actuated_breath_v1.py": "9db7da6e842f24b1959e452bf4d558f73da52bbf",
    "runtimes/tadash_body/anatomy_systems_v01.json": "0c3bd45e78d430b2ac91ddb80a5ba8987f73a397",
    "runtimes/tadash_body/audit_self_model.py": "dbde4acacd3f8306c032fd19d861d2be320db67c",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/renal_audit_v09.py": "07506c159a10cc2f221d8c776e8ad1f639f15dbf",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/renal_body_v09.py": "c5717167c623f88237764b9c991c837b7b90746e",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/renal_coupling_v09.py": "094f9495afacbfb76de8ee134ab32b345e09b806",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/renal_physiology_v09.py": "42c43d2a256564e8ae0e3a1f746dbbe4bf1dde55",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06/baseline/motion/sections.py": "9ad8c6c9162a97ecbbebeb2a978a79eb16609480",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06/baseline/pain/pain.py": "96008ac3311b2cb6586137853b15d685698ddb52",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06/baseline/pain/regions.json": "826e678297c96b9dc68808aa7d02008360939846",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06/bilateral_sections.py": "c7736be8f1ca4da03c5a39e3117e165a991d3fc5",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06/body_loop_v06.py": "947a25c3f2c5ff076d37d5fc0241be4408051673",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06/breath_motion_v06.py": "9459460aec7e707caf88db66c51d7ed1d401c072",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06/contact_design_v06.json": "2394080461f2ff6ea9e38ca0fae7628856026528",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06/contacts.py": "cb08c6c33a4670cb1ebd970a7728a7188ac6ab31",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06/hydraulic_table_v03.json": "0c39f91f3e8ed5f7b0abf0b4536b97df8fce8fc8",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06/pain_resilience_v04.py": "c05e1dc1c7dd43edcd7a27eda2002bf5dc38238f",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06/posture_step.py": "ea46f33508c4af7dc0b97616f44058b10c489a52",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06/resource_audit_v06.py": "c6304f09b57b5ae209c241415fae07c32c7d219d",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/brain_body_loop_v07.py": "97c8d7ae863d15bbb0b7cf38a443ec544564e74a",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/cognitive_workspace_v07.py": "60c0921fd646c5534ed77a0ff79193cfb86d8c7f",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/durable_memory_v08.py": "055912d9a55ffacc3631e51102b2c91e5ab3a767",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/interoception_v07.py": "0c303c8b3542b0e30eca03254b97aa6739824914",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/memory_body_loop_v08.py": "ed3f91ef5a791e653ae27d37e00a469d08b40820",
    "runtimes/tadash_body/decision_core.py": "abe1cd3c0d32e3591432345b92ab48fc49c4275b",
    "runtimes/tadash_body/persistent_embodiment_v1.py": "db87b7b1f47f33c443d803bb31b0c5f8e63af127",
    "runtimes/tadash_body/phenotype_v1.json": "61f61176c50379041ccbebf7a2f5d36824aa3a5a",
    "runtimes/tadash_body/privacy_boundary.py": "c75f0720751937bd7f095ce10e2caaf3307e5f55",
    "runtimes/tadash_body/retained_extensions/nasuraya_affective_layer_v01.py": "c9ec0fe1f0474d14f6c98c93c0131aa1c784cce5",
    "runtimes/tadash_body/retained_extensions/nasuraya_decision_core_v1.py": "de18284b6daea5c75dd479fc3a27ec643f9e4c2a",
    "runtimes/tadash_body/retained_extensions/nasuraya_emotion_spectrum_v01.py": "2b03e762e40659f68195627793db20e04f8465cc",
    "runtimes/tadash_body/retained_extensions/neural_circuit.py": "2f5b50de61ff387b4217c906adc203f8a2c421ba",
    "runtimes/tadash_body/synthetic_fixture.py": "241f15500e9b163681232e761bf92bc119418a0f",
    "runtimes/tadash_body/unified_body_v2.py": "7fd9a3139743c16f9bf1cc5067d8070c3facd62f",
    "examples/nasuraya_research/__init__.py": "24a6f57e8e242851a05c63079a1c594e828e1362",
    "examples/nasuraya_research/adapters.py": "7dccebd92690df190b6a297ca33c922f1283520a",
    "examples/nasuraya_research/body_observer.py": "cdb36b9b37d176a955c1a526d6b68b5d90026583",
    "examples/nasuraya_research/integrity.py": "90c6667a748c5ce662bfd175fb065d3d8efc57dc",
    "examples/nasuraya_research/native_snapshot.py": "b469e291b8d9cddbb135af2fa12de0da046d1177",
    "runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06/run_balance_checks.py": "38478becaa3cad833e43861626b132e9495f8b48"
}



def _blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def _sources(root):
    root = Path(root).resolve()
    result = {}
    for relative, expected in SOURCE_BLOBS.items():
        target = root / relative
        if target.is_symlink() or not target.resolve().is_relative_to(root):
            raise ValueError("native source symlink rejected: " + relative)
        try:
            raw = target.read_bytes()
        except OSError as error:
            raise ValueError("native source unavailable: " + relative) from error
        if _blob(raw) != expected:
            raise ValueError("native source hash mismatch: " + relative)
        result[relative] = raw
    return result


def _observe_staged(source_root):
    # This worker is entered only in a fresh interpreter with isolated sys.path.
    if not sys.platform.startswith("linux"):
        raise RuntimeError("native readout requires Linux; Windows uses exported JSON")
    source_root = Path(source_root).resolve()
    if (source_root.parent != Path(tempfile.gettempdir()).resolve()
            or not source_root.name.startswith("dios-native-readout-")
            or any((source_root / "runtimes/tadash_body/retained_extensions" / name).exists()
                   for name in ("trained_circuit.json", "initial_affect.json"))):
        raise ValueError("internal worker requires a fresh disposable source copy")
    source_before = _sources(source_root)
    repository = Path(__file__).resolve().parents[3]
    sys.path[:0] = [str(source_root / "runtimes/tadash_body"), str(source_root), str(repository)]
    from synthetic_fixture import prepare_defaults
    from memory_body_loop_v08 import MemoryBodyLoop
    from renal_coupling_v09 import RenalMemoryLoop, RenalPostureLoop
    from unified_body_v2 import UnifiedBody, PersistentEmbodiment
    from brain_body_loop_v07 import BrainBodyLoop
    from body_loop_v06 import BodyLoop
    from posture_step import PostureLoop
    from neural_circuit import Circuit
    import nasuraya_affective_layer_v01 as affect
    from examples.nasuraya_research.native_snapshot import snapshot
    from examples.nasuraya_research.body_observer import observe_native_body
    from examples.dios_nous.unified.body import project_native_snapshot, normalize_native, MODEL

    targets = [(UnifiedBody, "cycle"), (PersistentEmbodiment, "cycle"),
               (MemoryBodyLoop, "step"), (RenalMemoryLoop, "step"),
               (BrainBodyLoop, "step"), (BodyLoop, "step"),
               (PostureLoop, "step"), (RenalPostureLoop, "step"),
               (Circuit, "step"), (affect, "transition")]
    with ExitStack() as stack:
        guards = [stack.enter_context(patch.object(cls, method,
            side_effect=AssertionError("native dynamics forbidden"))) for cls, method in targets]
        # These two legacy filenames contain authored defaults, not trained data.
        prepare_defaults()
        memory = MemoryBodyLoop(context="synthetic-test", epoch="synthetic-v1")
        renal = RenalMemoryLoop.from_v08_checkpoint(memory.checkpoint())
        owner = PersistentEmbodiment.bootstrap(
            renal.checkpoint(), datetime(2026, 1, 1, tzinfo=timezone.utc))
        native = UnifiedBody.migrate(owner.checkpoint())
        before = deepcopy(native.checkpoint())
        observation = snapshot(native)
        research = observe_native_body(native, include_geometry=False)
        export = project_native_snapshot(observation, model_id=MODEL,
            finite_stocks=native.owner.body()["finite_stocks"])
        normalized = normalize_native(export, now_s=observation["time_s"])
        after = native.checkpoint()
        if before != after or observation["time_s"] != 0 or native.revision != 0:
            raise AssertionError("native readout changed state or advanced simulation")
        if any(guard.call_count for guard in guards):
            raise AssertionError("a forbidden dynamic entrypoint was called")
        source_after = _sources(source_root)
        if source_before != source_after:
            raise AssertionError("pinned native source changed")
        generated = {}
        for name in ("trained_circuit.json", "initial_affect.json"):
            raw = (source_root / "runtimes/tadash_body/retained_extensions" / name).read_bytes()
            generated[name] = dict(sha256=hashlib.sha256(raw).hexdigest(),
                status="fresh_authored_default_not_trained_or_user_state")
        result = dict(schema="dios.native_readout_receipt/1",
            execution_kind="executed_initial_simulation_readout",
            runtime_python_version=sys.version.split()[0],
            runtime_python_implementation=sys.implementation.name,
            runtime_platform=sys.platform,
            initialization="fresh_authored_defaults_without_synthetic_origin_warmup",
            source_commit=SOURCE_COMMIT,
            source_files={p: dict(git_blob_sha1=SOURCE_BLOBS[p], sha256=hashlib.sha256(raw).hexdigest())
                          for p, raw in source_before.items()},
            generated_defaults=generated,
            before_checkpoint_sha256=before["sha256"], after_checkpoint_sha256=after["sha256"],
            checkpoint_unchanged=True, before_after_equal=True, pinned_sources_unchanged=True,
            simulated_time_s=observation["time_s"], revision=native.revision,
            observation=observation, research_observer=research,
            export=export, native_export=deepcopy(export), normalized=normalized,
            guarded_dynamic_entrypoints=len(guards), forbidden_dynamic_calls=0,
            native_cycles_executed=0, action_requests_executed=0, model_api_calls=0,
            physical_sensor_connected=False,
            limitations=["fresh_initial_state_not_live_saved_user_body",
                "no_physiological_dynamics_executed", "no_empirical_validation",
                "legacy_195kg_not_calibrated_78kg", "no_geometry_or_torch_execution",
                "fresh_process_checkpoint_hash_varies_with_native_source_sequence_order",
                "cross_runtime_body_digest_bit_identity_not_claimed"])
        json.dumps(result, allow_nan=False)
        return result


def _worker(source_root):
    """Even direct internal CLI invocation cannot write caller-owned defaults."""
    if not sys.platform.startswith("linux"):
        raise RuntimeError("native readout requires Linux; Windows uses exported JSON")
    sources = _sources(source_root)
    with tempfile.TemporaryDirectory(prefix="dios-native-readout-") as temporary:
        copied_root = Path(temporary)
        for relative, raw in sources.items():
            destination = copied_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
        return _observe_staged(copied_root)


def execute_native_readout(source_root):
    """Verify pinned local sources, copy them, and read fresh state in isolation.

    Only a temporary directory receives generated fixture defaults and bytecode.
    The input source directory, live body checkpoints and server are untouched.
    """
    if not sys.platform.startswith("linux"):
        raise RuntimeError("native readout requires Linux; Windows uses exported JSON")
    sources = _sources(source_root)
    with tempfile.TemporaryDirectory(prefix="dios-native-readout-") as temporary:
        copied_root = Path(temporary)
        for relative, raw in sources.items():
            destination = copied_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
        completed = subprocess.run(
            [sys.executable, "-I", "-S", str(Path(__file__).resolve()), "--worker", str(copied_root)],
            capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
        if completed.returncode != 0:
            raise RuntimeError("native readout subprocess failed: " + completed.stderr[-4000:])
        result = json.loads(completed.stdout)
        if (_sources(source_root) != sources or result.get("checkpoint_unchanged") is not True
                or result.get("simulated_time_s") != 0 or result.get("forbidden_dynamic_calls") != 0):
            raise RuntimeError("native readout verification failed")
        return result


def run_readout(source_root=None):
    """Convenience entrypoint; defaults to this checkout's pinned native sources."""
    if source_root is None:
        source_root = Path(__file__).resolve().parents[3]
    return execute_native_readout(source_root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--export-output", type=Path,
                        help="Create the bounded JSON export for unified-demo or Windows")
    args = parser.parse_args()
    outputs = [p for p in (args.output, args.export_output) if p is not None]
    if len({p.resolve() for p in outputs}) != len(outputs):
        parser.error("receipt and export destinations must differ")
    if any(p.exists() or p.is_symlink() for p in outputs):
        parser.error("output already exists; readout was not started")
    result = _worker(args.worker) if args.worker is not None else execute_native_readout(args.source_root)
    raw = json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        # Creation is explicit; old evidence may not be silently overwritten.
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(raw)
    else:
        print(raw, end="")
    if args.export_output:
        args.export_output.parent.mkdir(parents=True, exist_ok=True)
        with args.export_output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(result["native_export"], ensure_ascii=False,
                                    allow_nan=False, sort_keys=True, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
