"""Source pinned spinal/sacral/tail feedback and non-actuation tests."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from .host import BodyLoop
from .experience import ExperienceController
from . import spinal_reflex

class SpinalReflexTests(unittest.TestCase):
    def test_native_encoder_source_and_nonmutation(self):
        with TemporaryDirectory() as tmp:
            with BodyLoop.start(Path(tmp)/"session.sqlite",max_actions=1) as loop:
                body=loop.body()
                before=body.checkpoint()["sha256"]
                sample=spinal_reflex.capture(body)
                self.assertEqual(sample["native_checkpoint_sha256"],before)
                result=spinal_reflex.preview(sample)
                self.assertIn(result["recommendation"],("walk","observe"))
                self.assertEqual(set(result["supported_feet"]).difference({"L","R"}),set())
                self.assertFalse(result["native_motor_command_executed"])
                self.assertFalse(result["physical_actuation"])
                self.assertEqual(body.checkpoint()["sha256"],before)

    def test_counterfactual_foot_contact_and_spinal_guard(self):
        with TemporaryDirectory() as tmp:
            with BodyLoop.start(Path(tmp)/"session.sqlite",max_actions=1) as loop:
                s=spinal_reflex.capture(loop.body())
        # These are explicit artificial stress fixtures, NOT native receipts.
        low=deepcopy(s)
        low["balance"]=.15
        self.assertEqual(spinal_reflex.preview(low)["recommendation"],"observe")
        for side in ("L","R"):
            unsupported=deepcopy(s)
            unsupported["feet"][side]["contact"]=False
            unsupported["feet"]["R" if side=="L" else "L"]["contact"]=False
            r=spinal_reflex.preview(unsupported)
            self.assertTrue(r["reflex_flags"]["missing_support"])
            self.assertEqual(r["recommendation"],"observe")
        tired=deepcopy(s)
        tired["fatigue"]=.95
        self.assertEqual(spinal_reflex.preview(tired)["recommendation"],"observe")
        self.assertIn(spinal_reflex.preview(s)["recommendation"],("walk","observe"))

    def test_every_experience_decision_references_spinal_sample(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/"session.sqlite"
            with BodyLoop.start(path,max_actions=1) as loop:
                c=ExperienceController.enable(loop)
                c.enable_workspace()
                c.enable_motivation(desire_proxy=.5)
                c.enable_neurovisceral()
                r=c.step("stance")
                self.assertIn("spinal_reflex",r["plan"])
                self.assertEqual(r["plan"]["spinal_reflex"]["native_checkpoint_sha256"],
                                 r["plan"]["neurovisceral"]["native_checkpoint_sha256"])
                self.assertTrue(r["plan"]["spinal_reflex"]["native_protection_remains_authoritative"])
                self.assertEqual(r["this_call_native_cycles"],1)
                self.assertFalse(c.status()["canonical_phenotype_alignment"]["solver_mass_changed"])

if __name__ == "__main__":
    unittest.main()
