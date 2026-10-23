"""No reference photos or private user images committed. All images synthetic."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from visual_genome.gate import image_info, inspect_candidate


class ImageGateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ref, self.cand = Path(tmp.name)/"ref.png", Path(tmp.name)/"candidate.png"
        Image.new("RGB", (200, 300), (30, 70, 90)).save(self.ref)
        Image.new("RGB", (200, 300), (90, 70, 30)).save(self.cand)
        self.rh = image_info(self.ref)["sha256"]
        self.ch = image_info(self.cand)["sha256"]

    def obs(self):
        regions = {}
        for name, count in (("left_hand", 5), ("right_hand", 5),
                            ("left_foot", 3), ("right_foot", 3)):
            regions[name] = {"bbox": [.2, .3, .4, .6], "visible": True,
                             "occluded": False, "detected_digits": count,
                             "fused_digits": False}
        return {"review": {"method": "manual_image_review", "reviewer_id": "test",
                           "reference_sha256": self.rh, "candidate_sha256": self.ch},
                "anatomy": regions,
                "face": {"bbox": [.2, .1, .5, .3], "visible": True,
                         "scar_on_left": False, "scar_on_right": True,
                         "matches_reference": True}}

    def test_no_report_is_not_pass(self):
        self.assertEqual(inspect_candidate(self.ref,self.rh,self.cand)["verdict"],"UNVERIFIED")

    def test_valid_manual_review_is_labeled_not_generator_proof(self):
        result = inspect_candidate(self.ref,self.rh,self.cand,self.obs())
        self.assertEqual(result["verdict"],"PASS")
        self.assertEqual(result["reference_used_by_generator"],"UNVERIFIED")

    def test_four_toed_right_foot_rejected(self):
        review = self.obs()
        review["anatomy"]["right_foot"]["detected_digits"] = 4
        r = inspect_candidate(self.ref,self.rh,self.cand,review)
        self.assertEqual(r["verdict"],"FAIL")

    def test_fused_hand_rejected(self):
        review = self.obs()
        review["anatomy"]["left_hand"]["fused_digits"] = True
        self.assertEqual(inspect_candidate(self.ref,self.rh,self.cand,review)["verdict"],"FAIL")

    def test_missing_hand_cannot_default_to_five(self):
        review = self.obs()
        del review["anatomy"]["right_hand"]
        self.assertEqual(inspect_candidate(self.ref,self.rh,self.cand,review)["verdict"],"UNVERIFIED")

    def test_cropped_toes_are_unverified(self):
        review = self.obs()
        review["anatomy"]["right_foot"]["bbox"] = [0.3,0.7,0.6,0.999]
        self.assertEqual(inspect_candidate(self.ref,self.rh,self.cand,review)["verdict"],"UNVERIFIED")

    def test_change_to_candidate_invalidates_review(self):
        review = self.obs()
        Image.new("RGB", (200,300), (255,255,255)).save(self.cand)
        self.assertEqual(inspect_candidate(self.ref,self.rh,self.cand,review)["verdict"],"UNVERIFIED")

    def test_changed_reference_blocks_all(self):
        review = self.obs()
        Image.new("RGB", (200,300), (255,255,255)).save(self.ref)
        self.assertEqual(inspect_candidate(self.ref,self.rh,self.cand,review)["reason"],"REFERENCE_HASH_MISMATCH")

    def test_missing_reference_blocks_all(self):
        self.ref.unlink()
        self.assertEqual(inspect_candidate(self.ref,self.rh,self.cand)["verdict"],"FAIL")

    def test_wrong_scar_side_rejected(self):
        review = self.obs()
        review["face"]["scar_on_left"] = True
        self.assertEqual(inspect_candidate(self.ref,self.rh,self.cand,review)["face_verdict"],"FAIL")

    def test_bogus_embedding_cannot_prove_identity(self):
        review = self.obs()
        del review["face"]["matches_reference"]
        review["face"]["embedding_cosine_similarity"] = .999
        self.assertEqual(inspect_candidate(self.ref,self.rh,self.cand,review)["face_verdict"],"UNVERIFIED")

    def test_forged_reference_hash_without_review_cannot_pass(self):
        review = self.obs()
        del review["review"]
        review["conditioned_on_reference_sha256"] = self.rh
        self.assertEqual(inspect_candidate(self.ref,self.rh,self.cand,review)["verdict"],"UNVERIFIED")


if __name__=="__main__":
    unittest.main()
