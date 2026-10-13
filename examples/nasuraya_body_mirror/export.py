"""Export verified, finite BodyLoop recordings for an offline body mirror.

Coordinates come from retained V06 inverse kinematics, not an animation rig.
The browser replays samples; it neither advances Tadash nor calls an API.
"""
import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def unpack(checkpoint):
    if digest(checkpoint['payload']) != checkpoint['sha256']:
        raise ValueError('body checkpoint digest mismatch')
    return checkpoint['payload']


def extract_run(directory, fixture):
    directory = Path(directory)
    records = json.loads((directory / 'decisions.json').read_text())['decisions']
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    if not records or len(records) != len(events):
        raise ValueError('complete finite recording required')
    frames = []
    for record, event in zip(records, events):
        if record['status'] != 'complete':
            raise ValueError('unfinished decision')
        outcome = record['actual_outcome']
        checkpoint = outcome['body_checkpoint']
        body = unpack(checkpoint)
        owner = unpack(body['owner'])
        retained = unpack(owner['owner'])
        legacy = unpack(retained['legacy_resource_and_cognitive_snapshot'])
        loop = unpack(legacy['loop'])
        physical = loop['last_body_frame']['posture']
        receipt = event['outcome']
        observation = receipt['self_model_after']
        if (observation['checkpoint_sha256'] != checkpoint['sha256'] or
            receipt['decision_id'] != record['id'] or
            receipt['requested_action'] != record['selected_action'] or
            receipt['actual_action'] != outcome['selected_action']):
            raise ValueError('recording receipt and checkpoint disagree')
        for side in ('L', 'R'):
            pose = physical['kinematics'][side]
            if not pose['reachable'] or pose['segment_length_error_m'] > 1e-8:
                raise ValueError('invalid retained kinematics')
            if not all(math.isfinite(v) for point in pose['joints_m'].values() for v in point):
                raise ValueError('non-finite pose')
        frames.append(dict(revision=body['revision'], checkpoint_sha256=checkpoint['sha256'],
            simulated_wall_utc=observation['simulated_wall_utc'],
            requested=record['selected_action'], actual=outcome['selected_action'],
            recalled=len(record['recalled_feedback_ids']), state=observation['minimum_state'],
            phase=physical['phase'], walk_steps=physical['walk_steps'], com_m=physical['com_m'],
            feet_m=physical['feet_m'], tail_angle_rad=physical['tail_angle_rad'],
            joints_m={s: physical['kinematics'][s]['joints_m'] for s in ('L', 'R')}))
    return dict(fixture=fixture, frames=frames, recording_hashes={name:
        sha256((directory / name).read_bytes()).hexdigest()
        for name in ('decisions.json', 'events.jsonl', 'summary.json')})


def export(runs, output):
    design_path = ROOT / 'runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06/contact_design_v06.json'
    design = json.loads(design_path.read_text())
    data = dict(schema='nasuraya-body-mirror/1', scope='recorded synthetic software-body runs',
        runtime_manifest_sha256=sha256((ROOT / 'runtimes/tadash_body/PUBLIC_FILES_SHA256.json').read_bytes()).hexdigest(),
        coordinate_axes='+X left; +Y forward; +Z up; metres',
        geometry_source='retained V06 three-link inverse kinematics',
        interpolation_scope='visual interpolation only; no intermediate simulated states',
        upper_body_scope='schematic drawing, not measured or actuated anatomy',
        design={k: design[k] for k in ('patches', 'leg_lengths_m', 'tail_length_m', 'com_height_m')},
        scenarios={f: extract_run(Path(runs) / f, f) for f in ('normal', 'sleep')})
    Path(output).write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':'))+'\n')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--generate', action='store_true')
    args = parser.parse_args()
    if args.generate:
        for fixture in ('normal', 'sleep'):
            subprocess.run([sys.executable, '-m', 'examples.nasuraya_body_loop', 'demo',
                '--fixture', fixture, '--max-actions', '12', '--steps', '12',
                '--duration-s', '1', '--output-dir', str((args.runs / fixture).resolve())],
                cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    data = export(args.runs, args.output)
    print(json.dumps({'schema': data['schema'], 'frames': sum(len(s['frames']) for s in data['scenarios'].values())}))


if __name__ == '__main__':
    main()
