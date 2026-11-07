"""Canonical appearance and physical-solver divergence stays explicit."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from .host import BodyLoop
from . import phenotype_alignment

class CanonicalPhenotypeTests(unittest.TestCase):
    def test_canonical_shape_does_not_rewrite_native_body(self):
        with TemporaryDirectory() as tmp:
            with BodyLoop.start(Path(tmp)/"session.sqlite", max_actions=1) as loop:
                body=loop.body()
                h=body.checkpoint()["sha256"]
                result=phenotype_alignment.read(body)
                self.assertEqual(h,result["native_checkpoint_sha256"])
                self.assertEqual(h,body.checkpoint()["sha256"])
                c=result["canonical_visual_contract"]
                old=result["historical_solver_atlas"]
                self.assertEqual(c["crown_height_cm_excluding_horns"],170.0)
                self.assertEqual(c["horn_tip_height_cm"],192.0)
                self.assertEqual(c["mass_kg"],78.0)
                self.assertEqual(c["tail_centerline_cm"],85.0)
                self.assertEqual(c["fingers_per_hand"],5)
                self.assertEqual(c["toes_per_foot"],3)
                self.assertEqual(c["blue_fox"],"totem_not_anatomy")
                self.assertEqual(old["crown_height_cm"],250)
                self.assertEqual(old["mass_kg"],195)
                self.assertEqual(old["horn_tip_height_cm"],268)
                self.assertEqual(old["tail_centerline_cm"],120)
                self.assertEqual(len(old["phenotype_manifest_verified_sha256"]),64)
                self.assertAlmostEqual(result["appearance_scale_only"],.68)
                self.assertFalse(result["solver_mass_changed"])
                self.assertFalse(result["solver_inertia_or_gravity_changed"])
                self.assertFalse(result["canonical_3d_collision_and_clearance_validated"])
                self.assertTrue(result["safe_for_geometry_annotation_only"])
                pose=result["visual_landmark_projection_m"]
                self.assertIn("pelvis",pose)
                self.assertIn("tail",pose)
                self.assertIn("foot_L",pose)
                self.assertIn("foot_R",pose)
                self.assertIn("horn_L",pose)
                self.assertIn("horn_R",pose)

if __name__ == "__main__":
    unittest.main()
