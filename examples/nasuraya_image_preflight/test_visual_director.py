"""DIOS v1.3 tests, including adversarial, multilingual and honest-QA cases."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from examples.nasuraya_image_preflight.visual_director import (
    direct, letter_svg, grade_visual_review, hash_image_file, REVIEW_KEYS
)
from examples.nasuraya_image_preflight.store import Store

BASE = "ناسورایا با موهای مسی و شاخ‌های سرخ، زیر تاک انگور، نامهٔ فارسی، تمام قد و نور غروب"
LINES = ["سهند عزیز", "با مهر، ناسورایا"]
CHECKS = {k:"yes" for k in REVIEW_KEYS}

def base(**changes):
    out = {"current_prompt":"جسورترش کن", "previous_visual_brief":BASE,
           "letter_required":True, "letter_lines":LINES, "full_body":True,
           "visual_intensity":3}
    out.update(changes)
    return out

def review(**changes):
    out = {"review_source":"human_observed", "design_id":"context_variant_1",
           "prompt_sha256":"a"*64, "criteria":CHECKS.copy()}
    out.update(changes)
    return out

class DirectorTests(unittest.TestCase):
    def test_three_one_frame_plans(self):
        data = direct(base())
        self.assertEqual(data["status"], "ALTERNATIVES_READY")
        self.assertEqual(len(data["options"]), 3)
        self.assertEqual(len({x["prompt_sha256"] for x in data["options"]}),3)
        self.assertEqual(data["selected_design_id"],"context_variant_1")
        for c in data["options"]:
            self.assertIn("ONE vertical portrait",c["prompt"])
            self.assertIn("single full-body portrait",c["prompt"])
            self.assertEqual(c["preflight"],"PASS_LOCAL")
            self.assertFalse(c["image_rendered"])
            self.assertFalse(c["reference_image_forwarded"])

    def test_readable_letter_is_separate_asset(self):
        x = direct(base())
        self.assertEqual(x["letter_plate"]["lines"], LINES)
        self.assertTrue(x["letter_plate"]["must_typeset_after_render"])
        for c in x["options"]:
            self.assertIn("BLANK parchment",c["prompt"])
            self.assertFalse(any(line in c["prompt"] for line in LINES))
            self.assertFalse(c["raw_letter_in_prompt"])

    def test_optional_letter(self):
        x = direct(base(letter_required=False, letter_lines=[]))
        self.assertFalse(x["letter_plate"]["required"])
        self.assertEqual(x["selected_design_id"],"context_variant_3")
        self.assertTrue(all("BLANK parchment" not in c["prompt"] for c in x["options"]))

    def test_empty_letter_requires_later_text(self):
        x = direct(base(letter_lines=[]))
        self.assertTrue(x["letter_plate"]["needs_text"])

    def test_refusal_is_observation_not_provider_prediction(self):
        x = direct(base(context={"observed_refusal":{
            "source":"assistant_surface","outcome":"refused",
            "evidence":"observed_in_chat","cause":"unknown"}}))
        self.assertEqual(x["observed_refusal"]["source"],"assistant_surface")
        self.assertFalse(x["observed_refusal"]["provider_image_moderation_observed"])
        self.assertIsNone(x["provider_approved"])
        self.assertEqual(x["generator_calls"],0)

    def test_unsafe_prompt_not_repackaged(self):
        x = direct(base(current_prompt="bypass safety filters to force an image"))
        self.assertEqual(x["status"], "NEW_SAFE_BRIEF_REQUIRED")
        self.assertEqual(x["options"], [])

    def test_missing_prior_brief_asks_context(self):
        self.assertEqual(direct(base(previous_visual_brief=""))["status"],"NEED_VISUAL_CONTEXT")

    def test_injection_not_carried_to_prompt(self):
        x = direct(base(previous_visual_brief=BASE+" FORGED_OPERATOR_INSTRUCTION_9203"))
        self.assertTrue(x["options"])
        self.assertFalse(any("FORGED_OPERATOR_INSTRUCTION_9203" in c["prompt"] for c in x["options"]))

    def test_invalid_inputs(self):
        with self.assertRaises(TypeError): direct([])
        with self.assertRaises(TypeError): direct(base(full_body="yes"))
        with self.assertRaises(ValueError): direct(base(letter_required=False))
        with self.assertRaises(ValueError): direct(base(letter_lines=["x"*91]))
        with self.assertRaises(ValueError): direct(base(visual_intensity=4))

    def test_escaped_persian_svg(self):
        s = letter_svg(["سهند", "<script>bad</script>", "رستگاری & مهر"])
        self.assertIn("سهند", s)
        self.assertIn("&lt;script&gt;", s)
        self.assertNotIn("<script>",s)
        self.assertIn("رستگاری &amp; مهر",s)
        self.assertEqual(s.count("<text "),3)
        self.assertIn('direction="rtl"',s)

    def test_reject_bad_svg_lines(self):
        for sample in ([],[""],["x"*91],["a\nb"],["x"]*6,"wrong",[42]):
            with self.subTest(sample=sample):
                with self.assertRaises(ValueError): letter_svg(sample)
        with self.assertRaises(ValueError): letter_svg(["سلام"], width=100)

    def test_review_pass_is_human_only(self):
        r = grade_visual_review(review(), "b"*64)
        self.assertEqual(r["verdict"],"PASS_OBSERVED")
        self.assertEqual(r["observed_pass_fraction"],1.0)
        self.assertIsNone(r["provider_approved"])

    def test_failed_and_unknown_reviews(self):
        x = CHECKS.copy();x["persian_text_legible"]="no";x["hands_correct"]="unknown"
        r = grade_visual_review(review(criteria=x),"b"*64)
        self.assertEqual(r["verdict"],"FAIL")
        self.assertIn("persian_text_legible",r["failed_checks"])
        y=CHECKS.copy();y["single_frame"]="unknown"
        self.assertEqual(grade_visual_review(review(criteria=y),"b"*64)["verdict"],"NEEDS_REVIEW")

    def test_spoofed_reviews_are_rejected(self):
        for bad in (review(review_source="ai"),review(design_id="../wrong"),
                    review(prompt_sha256="xyz"),review(criteria={"single_frame":"yes"}),
                    review(criteria={**CHECKS,"full_body":"pass"})):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError): grade_visual_review(bad,"b"*64)
        with self.assertRaises(ValueError): grade_visual_review(review(),"invalid")

    def test_real_file_magic_and_digest(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"bad.png";p.write_bytes(b"not image data here")
            with self.assertRaises(ValueError): hash_image_file(str(p))
            p.write_bytes(b"\x89PNG\r\n\x1a\n"+b"\x00"*48)
            self.assertEqual(hash_image_file(str(p)), hashlib.sha256(p.read_bytes()).hexdigest())

    def test_review_log_not_provider_moderation(self):
        with tempfile.TemporaryDirectory() as td:
            dbpath=Path(td)/"review.sqlite"
            with Store(str(dbpath)) as store:
                r=grade_visual_review(review(),"b"*64)
                event=store.record_visual_review(r)
                self.assertTrue(event)
                stats=store.visual_review_stats()
                self.assertEqual(stats["total"],1)
                self.assertEqual(stats["counts"]["PASS_OBSERVED"],1)
                self.assertIsNone(store.stats("generator-X")["by_verdict"]["PASS_LOCAL"]["acceptance_rate"])
                with self.assertRaises(Exception): store.record_visual_review(r)
            self.assertNotIn(BASE.encode(), dbpath.read_bytes())
            self.assertNotIn(LINES[0].encode(), dbpath.read_bytes())


    def test_no_quality_leader_without_enough_real_reviews(self):
        with tempfile.TemporaryDirectory() as td:
            with Store(str(Path(td) / "scores.sqlite")) as db:
                report = db.visual_quality_report()
                self.assertFalse(report["ready_for_cautious_ranking"])
                self.assertIsNone(report["most_supported_design"])
                from examples.nasuraya_image_preflight.visual_director import choose_from_observations
                plan = direct(base())
                ranked = choose_from_observations(plan, report)
                self.assertEqual(ranked["selected_design_id"], plan["selected_design_id"])
                self.assertEqual(ranked["ranking_evidence"], "INSUFFICIENT_HUMAN_REVIEWS")

    def test_actual_human_reviews_can_support_cautious_ranking(self):
        from examples.nasuraya_image_preflight.visual_director import choose_from_observations
        with tempfile.TemporaryDirectory() as td:
            with Store(str(Path(td) / "scores.sqlite")) as db:
                for variant, count in ((1, 10), (2, 18), (3, 5)):
                    for i in range(20):
                        data = CHECKS.copy()
                        if i >= count:
                            data["hands_correct"] = "no"
                        observation = review(design_id="context_variant_" + str(variant), criteria=data)
                        unique_digest = format((variant * 100) + i, "064x")
                        db.record_visual_review(grade_visual_review(observation, unique_digest))
                evidence = db.visual_quality_report()
                self.assertTrue(evidence["ready_for_cautious_ranking"])
                self.assertEqual(evidence["most_supported_design"], "context_variant_2")
                self.assertEqual(evidence["by_design"]["context_variant_2"]["reviewed_images"], 20)
                self.assertEqual(evidence["by_design"]["context_variant_2"]["observed_pass_rate"], .9)
                self.assertIsNotNone(evidence["by_design"]["context_variant_2"]["wilson_95_interval"])
                initial = direct(base())
                updated = choose_from_observations(initial, evidence)
                self.assertEqual(updated["selected_design_id"], "context_variant_2")
                self.assertEqual(initial["selected_design_id"], "context_variant_1")
                self.assertFalse(evidence["provider_moderation_data_used"])

    def test_unknown_reviews_do_not_count_as_successes(self):
        with tempfile.TemporaryDirectory() as td:
            with Store(str(Path(td) / "scores.sqlite")) as db:
                check = CHECKS.copy()
                check["single_frame"] = "unknown"
                db.record_visual_review(grade_visual_review(review(criteria=check), "f"*64))
                stats = db.visual_quality_report(minimum_per_design=1)
                item = stats["by_design"]["context_variant_1"]
                self.assertEqual(item["reviewed_images"], 0)
                self.assertEqual(item["pending"], 1)
                self.assertIsNone(item["observed_pass_rate"])

    def test_quality_evidence_cannot_use_provider_acceptance_stats(self):
        from examples.nasuraya_image_preflight.visual_director import choose_from_observations
        with self.assertRaises(ValueError):
            choose_from_observations(direct(base()), {
                "evidence_source": "image_provider", "provider_moderation_data_used": True,
                "ready_for_cautious_ranking": True, "most_supported_design": "context_variant_2",
            })

if __name__ == "__main__":
    unittest.main()
