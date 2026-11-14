"""Deterministic offline tests for the future server phase-1 job."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from tools.bridge_jobs import nasu_wholebody_phase1 as job

ROOT = Path(__file__).resolve().parents[1]


class ServerPhaseOneTests(unittest.TestCase):
    def test_offline_server_workspace_generates_real_97_node_inventory(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "whole_body"
            with mock.patch.object(job, "fetch_pinned", side_effect=AssertionError("network")):
                receipt = job.run_inventory(ROOT, workspace)
            self.assertIn("NODES=97;SYSTEMS=12;ROUTES=31", receipt)
            self.assertIn("PHYSICS=UNVERIFIED", receipt)
            report = json.loads((workspace / "output" / "registry.json").read_text(encoding="utf-8"))
            gaps = json.loads((workspace / "output" / "gaps.json").read_text(encoding="utf-8"))
            self.assertEqual(len(report["nodes"]), 97)
            self.assertEqual(gaps["route_physical_validations_remaining"], 31)
            self.assertFalse(report["safety"]["physical_actuation"])
            # A cold second invocation does not replace an existing receipt.
            self.assertEqual(receipt, job.run_inventory(ROOT, workspace))

    def test_source_pinning_detects_modified_canonical_tool(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "untrusted"
            for _, relative, _ in job.PINNED:
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, destination)
            changed = root / "tools" / "fullbody_design_atlas.py"
            changed.write_bytes(changed.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "source_pin_mismatch"):
                job.run_inventory(root, Path(td) / "workspace")

    def test_only_three_pinned_public_repo_files(self):
        self.assertEqual(len(job.PINNED), 3)
        for commit, path, digest in job.PINNED:
            self.assertEqual(len(commit), 40)
            self.assertEqual(len(digest), 40)
            self.assertNotIn("..", path)
        self.assertEqual(len({p for _, p, _ in job.PINNED}), 3)

    def test_safe_summary_rejects_commands_and_accepts_lowercase_hashes(self):
        self.assertTrue(job.SUMMARY.fullmatch(
            "ATLAS=INVENTORY;NODES=97;REG=ab53e317d02a"))
        self.assertFalse(job.SUMMARY.fullmatch("TOKEN=secret\nrm -rf /"))
        self.assertFalse(job.SUMMARY.fullmatch("foo;bar;".join(["x"] * 100)))

    def test_rejects_tampered_existing_cached_source(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            path = ws / "source" / "runtimes/tadash_body/phenotype_v1.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"not-our-phenotype")
            with self.assertRaisesRegex(ValueError, "source_pin_mismatch"):
                job.run_inventory(ROOT, ws)

    def test_no_implicit_server_task_or_network_action_in_offline_mode(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(job, "fetch_pinned", side_effect=AssertionError("unexpected network")):
                receipt = job.run_inventory(ROOT, Path(td))
            self.assertTrue(receipt.startswith("ATLAS=INVENTORY;"))
            self.assertTrue((Path(td) / "output" / "registry.json").exists())


if __name__ == "__main__":
    unittest.main()
