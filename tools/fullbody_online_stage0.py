#!/usr/bin/env python3
"""Read-only anatomy inventory + bounded HTTPS source probes.

This stage neither builds a body nor mutates existing body state. No third-party
model/API, local service, scheduler, credentials, or downloaded executable.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import ssl
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ANATOMY = ROOT / 'runtimes/tadash_body/anatomy_systems_v01.json'
MAX_SAMPLE_BYTES = 65536
TIMEOUT_SECONDS = 8
SOURCES = (
    ('nlm_vhp', 'https://www.nlm.nih.gov/research/visible/visible_human.html', 'human anatomical reference'),
    ('nih_3d', 'https://3d.nih.gov/terms', 'asset-specific licensing; educational reference'),
    ('opensim', 'https://opensimconfluence.atlassian.net/wiki/spaces/OpenSim/pages/53089741', 'musculoskeletal scaling and dynamics methods'),
    ('mujoco', 'https://mujoco.readthedocs.io/en/stable/', 'contact and sensor modeling methods'),
)
ALLOWED_HOSTS = frozenset(urllib.parse.urlsplit(s[1]).hostname for s in SOURCES)
FIELDS = ('volume_geometry', 'tissue_layers', 'bone_fascial_attachment', 'artery',
          'vein', 'lymph', 'sensory_nerve', 'motor_nerve', 'autonomic_nerve',
          'load_motion', 'thermal_water_energy', 'control', 'clearance_collision',
          'validation_evidence')
TARGET = {
    'crown_height_cm': 170, 'horn_tip_height_cm': 192, 'mass_kg': 78,
    'tail_centerline_cm': 85, 'horns': 2, 'fingers_per_hand': 5,
    'toes_per_foot': 3, 'digitigrade': True,
    'feminine_contour_without_extra_visible_bulking': True,
    'resonan_at_both_horn_roots': True, 'spandar_on_thymic_capsule': True,
    'azarine_left_flank': True,
}


def approved_url(url):
    parsed = urllib.parse.urlsplit(url)
    return (parsed.scheme == 'https' and parsed.hostname in ALLOWED_HOSTS
            and not parsed.username and not parsed.password and parsed.port in (None, 443))


class ApprovedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not approved_url(newurl):
            raise ValueError('redirect_to_unapproved_host')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def probe(source, opener=None):
    sid, url, purpose = source
    record = {'id': sid, 'url': url, 'purpose': purpose,
              'checked_utc': datetime.now(timezone.utc).isoformat(),
              'network_status': 'UNKNOWN', 'measured_anatomy': False,
              'license_verified_for_asset': False}
    if not approved_url(url):
        record['network_status'] = 'BLOCKED_URL'
        return record
    if opener is None:
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
            ApprovedRedirect())
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'Zohraya-BodyResearch-ReadOnly/0.1',
                                                       'Accept': 'text/html'})
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            if not approved_url(response.geturl()):
                raise ValueError('unapproved_final_url')
            data = response.read(MAX_SAMPLE_BYTES + 1)
            record.update(network_status='HTTPS_REACHABLE', http_status=response.status,
                          content_type=response.headers.get('Content-Type', '').split(';')[0],
                          sampled_bytes=min(len(data), MAX_SAMPLE_BYTES),
                          sample_truncated=len(data) > MAX_SAMPLE_BYTES,
                          sample_sha256=hashlib.sha256(data[:MAX_SAMPLE_BYTES]).hexdigest())
    except urllib.error.HTTPError as exc:
        record.update(network_status='HTTP_ERROR', http_status=exc.code)
    except (ValueError, urllib.error.URLError, TimeoutError, OSError) as exc:
        record['network_status'] = 'NETWORK_ERROR'
        record['error_type'] = type(exc).__name__
    return record


def inventory(anatomy_path):
    raw = Path(anatomy_path).read_bytes()
    data = json.loads(raw)
    observed = {x: len(data.get(x, [])) for x in ('systems', 'nodes', 'routes')}
    if observed != {'systems': 12, 'nodes': 97, 'routes': 31}:
        raise ValueError('baseline_anatomy_counts_mismatch: ' + str(observed))
    if len({x['id'] for x in data['nodes']}) != 97:
        raise ValueError('duplicate_anatomy_node_ids')
    old_scale = data.get('baseline_contract', {}).get('adult_scale', {})
    original = data.get('baseline_contract', {}).get('phenotype_contract', {})
    if (original.get('horns') != 2 or original.get('toes_per_foot') != 3 or
            original.get('digitigrade') is not True):
        raise ValueError('baseline_morphology_conflict')
    baseline = {'source_path': 'runtimes/tadash_body/anatomy_systems_v01.json',
                'source_sha256': hashlib.sha256(raw).hexdigest(),
                'existing_counts': observed, 'canonical_design_target': TARGET,
                'legacy_native_scale_unmodified': old_scale,
                'note': 'Target 170/78 != old native 250/195; no rescaling performed.',
                'existing_body_or_memory_mutated': False}
    gaps = {'status': 'INVENTORY_ONLY_NOT_GEOMETRY',
            'nodes': [{'id': x['id'], 'requirements': {k: 'UNVERIFIED' for k in FIELDS}}
                      for x in data['nodes']],
            'separate_additional_parts': 'See Issue #180 and PR #181. No 3D details synthesized.',
            'mechanical_test_status': 'NOT_EXECUTED',
            'physiology_test_status': 'NOT_EXECUTED'}
    return baseline, gaps


def run(anatomy_path, output_dir, online=False, probe_func=probe):
    baseline, gaps = inventory(anatomy_path)
    sources = [probe_func(s) for s in SOURCES] if online else [
        {'id': sid, 'url': url, 'purpose': role, 'network_status': 'NOT_CHECKED_OFFLINE',
         'measured_anatomy': False, 'license_verified_for_asset': False}
        for sid, url, role in SOURCES]
    if any(x.get('measured_anatomy') for x in sources):
        raise ValueError('source_probe_cannot_claim_anatomical_measurement')
    report = {'run_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'read_only_stage0',
              'validation': 'BASELINE_COUNTS_AND_MORPHOLOGY_CHECKED',
              'network_reachability': {s['id']: s['network_status'] for s in sources},
              'model_completed': False, 'live_morphology_changed': False,
              'approvals_required_before_any_model_change': True}
    output_dir = Path(output_dir)
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    files = {
        'baseline_contract.json': baseline, 'source_registry.json': {'sources': sources},
        'geometry_and_physics_gaps.json': gaps,
        'candidate_changes.json': {'status': 'AWAITING_REVIEW', 'candidates': [],
                                   'approval_rule': 'No canonical morphology changes without owner approval'},
        'validation_results.json': report,
    }
    for name, payload in files.items():
        with (output_dir / name).open('x', encoding='utf-8') as out:
            json.dump(payload, out, ensure_ascii=False, indent=2, sort_keys=True)
            out.write('\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--anatomy', type=Path, default=ANATOMY)
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='new, not yet existing directory only')
    parser.add_argument('--online', action='store_true',
                        help='bounded read-only HTTPS documentation probes only')
    args = parser.parse_args()
    print(json.dumps(run(args.anatomy, args.output_dir, args.online), sort_keys=True))


if __name__ == '__main__':
    main()
