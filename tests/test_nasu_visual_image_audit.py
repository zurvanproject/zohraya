"""Image-review audit contracts. Do NOT mistake annotations for raster recognition."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('visual_audit', HERE / 'tools/nasu_visual_image_audit.py')
audit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_mod)
AUDIT = audit_mod.audit


def foot(side, view='dorsal'):
    return {'side': side, 'visible': True, 'view': view,
            'digital_toes': 3, 'digital_pads': 3 if view == 'plantar' else None,
            'terminal_claws': 3,
            'central_metatarsal_pad': 1 if view == 'plantar' else None}


def clean_record():
    return {'schema': 'nasuraya.visual-manual-image-audit/1',
            'image_sha256': '0'*64,
            'all_panels_reviewed': True,
            'panels': [
               {'kind':'sole', 'feet':[foot('left', 'plantar')], 'performance_claims_present':False},
               {'kind':'sitting', 'feet':[foot('left'), foot('right')],
                'pelvis_supported':True,'human_lotus_or_crossleg_pose':False,
                'knee_hock_metatarsal_chain_visible':True,
                'toe_pads_grounded':True,'performance_claims_present':False}]}


class ImageReviewGate(unittest.TestCase):
    def test_user_reported_original_collage_rejected(self):
        path = HERE / 'docs/visual/evidence/rejected_body_suite_20261115.json'
        errors = AUDIT(json.loads(path.read_text(encoding='utf-8')))
        self.assertTrue(any('digital_toes' in item for item in errors))
        self.assertTrue(any('digital_pads' in item for item in errors))
        self.assertTrue(any('human_crossleg_pose' in item for item in errors))
        self.assertTrue(any('unsupported_performance_badges' in item for item in errors))
    def test_clean_annotated_reference_contract(self):
        self.assertEqual(AUDIT(clean_record()), [])
    def test_fourth_toe_rejected_in_small_closeup(self):
        doc = clean_record()
        doc['panels'][0]['feet'][0]['digital_toes'] = 4
        self.assertIn('panel_0:left_digital_toes',AUDIT(doc))
    def test_extra_fourth_digital_pad_rejected(self):
        doc = clean_record()
        doc['panels'][0]['feet'][0]['digital_pads'] = 4
        self.assertIn('panel_0:left_digital_pads',AUDIT(doc))
    def test_invisible_sole_data_cannot_be_assumed(self):
        doc = clean_record()
        doc['panels'][1]['feet'][0]['digital_pads'] = 3
        self.assertIn('panel_1:left_inferred_invisible_pads', AUDIT(doc))
    def test_two_leg_sitting_requires_two_visible_feet(self):
        doc = clean_record()
        doc['panels'][1]['feet'].pop()
        self.assertIn('panel_1:insufficient_feet', AUDIT(doc))
    def test_human_lotus_pose_rejected(self):
        doc = clean_record()
        doc['panels'][1]['human_lotus_or_crossleg_pose'] = True
        self.assertIn('panel_1:human_crossleg_pose',AUDIT(doc))
    def test_obscured_joint_chain_is_unverified(self):
        doc = clean_record()
        doc['panels'][1]['knee_hock_metatarsal_chain_visible'] = False
        self.assertIn('panel_1:joint_chain_hidden',AUDIT(doc))
    def test_fictitious_metrics_rejected(self):
        doc = clean_record()
        doc['panels'][0]['performance_claims_present'] = True
        self.assertIn('panel_0:unsupported_performance_badges',AUDIT(doc))
    def test_incomplete_collage_not_accepted(self):
        doc = clean_record()
        doc['all_panels_reviewed'] = False
        self.assertIn('collage_not_exhaustively_reviewed',AUDIT(doc))


if __name__ == '__main__':
    unittest.main()
