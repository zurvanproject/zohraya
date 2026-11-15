#!/usr/bin/env python3
"""Strict reviewer-annotation gate for generated images.

Validates human/provided per-panel observations, NOT the image pixels.
No computer vision is used; review annotations MUST be checked against pixels.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

KINDS = {'portrait', 'standing', 'walking', 'running', 'crouching', 'sitting',
         'ritual', 'sole', 'joint_closeup'}
FEET_REQUIRED = {'standing': 2, 'sitting': 2, 'ritual': 2, 'sole': 1,
                 'joint_closeup': 1}


def audit(review: dict) -> list[str]:
    errors = []
    if review.get('schema') != 'nasuraya.visual-manual-image-audit/1':
        errors.append('schema')
    digest = review.get('image_sha256')
    if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
        errors.append('image_digest')
    panels = review.get('panels')
    if not isinstance(panels, list) or not panels:
        return errors + ['missing_panels']
    for i, panel in enumerate(panels):
        label = 'panel_' + str(i) + ':'
        kind = panel.get('kind')
        if kind not in KINDS:
            errors.append(label + 'unknown_kind')
            continue
        feet = panel.get('feet')
        if not isinstance(feet, list):
            errors.append(label + 'feet_not_reviewed')
            continue
        ids = set()
        for j, foot in enumerate(feet):
            fid = foot.get('side')
            if fid not in ('left', 'right') or fid in ids:
                errors.append(label + 'invalid_foot_side')
            ids.add(fid)
            for field in ('digital_toes', 'digital_pads', 'terminal_claws'):
                count = foot.get(field)
                if type(count) is not int or count != 3:
                    errors.append(label + fid + '_' + field)
            if kind == 'sole' and foot.get('central_metatarsal_pad') != 1:
                errors.append(label + fid + '_central_pad')
            if foot.get('visible') is not True:
                errors.append(label + fid + '_not_visible')
        req = FEET_REQUIRED.get(kind, 0)
        if len(feet) < req:
            errors.append(label + 'insufficient_feet')
        if kind in ('sitting', 'ritual'):
            if panel.get('human_lotus_or_crossleg_pose') is not False:
                errors.append(label + 'human_crossleg_pose')
            if panel.get('pelvis_supported') is not True:
                errors.append(label + 'no_seat_support')
            if panel.get('knee_hock_metatarsal_chain_visible') is not True:
                errors.append(label + 'joint_chain_hidden')
            if panel.get('toe_pads_grounded') is not True:
                errors.append(label + 'ground_contact_unverified')
        if kind == 'standing' and panel.get('knee_hock_metatarsal_chain_visible') is not True:
            errors.append(label + 'joint_chain_hidden')
        if panel.get('performance_claims_present') is True:
            ref = panel.get('performance_evidence_ref')
            if not isinstance(ref, str) or not ref.strip():
                errors.append(label + 'unsupported_performance_badges')
        if panel.get('performance_claims_present') is not True and panel.get('performance_claims_present') is not False:
            errors.append(label + 'claims_not_reviewed')
    if review.get('all_panels_reviewed') is not True:
        errors.append('collage_not_exhaustively_reviewed')
    return errors


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python3 nasu_visual_image_audit.py /path/to/image_review.json')
    doc = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    errors = audit(doc)
    print(json.dumps({'status': 'REJECT' if errors else 'ANNOTATION_CONTRACT_PASS',
                      'errors': errors}, ensure_ascii=False, indent=2))
    # Note: a zero exit proves only that REVIEWED ANNOTATIONS are consistent,
    # not that annotators correctly counted from the raster image.
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
