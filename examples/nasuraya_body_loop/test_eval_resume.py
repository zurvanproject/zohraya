"""Exercise boundary recovery against a completed smoke run and corrupt copies."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .__main__ import ROOT

COMPARE = ('schema','profile','native_cycles','split_counts','selected_config','heldout',
           'by_fold','novel_duration','by_step','relative_brier_reduction_vs_v1',
           'acceptance_criteria','all_acceptance_criteria_passed','validation_passed',
           'evidence_checks','protocol_sha256','limitations')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('--proof',type=Path,required=True)
    args=parser.parse_args(argv);source=args.source.resolve()
    expected=json.loads((source/'summary.json').read_text())
    if expected['profile']!='smoke' or expected['native_cycles']!=132 or not expected['validation_passed']:
        raise ValueError('completed current-source smoke evidence required')
    boundary=expected['split_counts']['train']+expected['split_counts']['validation']
    with tempfile.TemporaryDirectory(prefix='nasuraya-resume-contract-') as tmp:
        tmp=Path(tmp);damaged=tmp/'damaged';shutil.copytree(source,damaged)
        path=damaged/'predictions.jsonl';lines=path.read_text().splitlines()
        del lines[boundary+1]
        path.write_text('\n'.join(lines)+'\n')
        result=tmp/'resumed'
        call=subprocess.run([sys.executable,'-m','examples.nasuraya_body_loop.resume_continuous_eval',
            str(damaged),str(result)],cwd=ROOT,text=True,capture_output=True)
        if call.returncode:raise RuntimeError(call.stdout+call.stderr)
        actual=json.loads((result/'summary.json').read_text())
        for key in COMPARE:
            if actual[key]!=expected[key]:raise AssertionError('resumption differs: '+key)
        if actual['new_native_cycles']!=36 or actual['reused_prefix_cycles']!=96:
            raise AssertionError('resumption counts differ')
        lines=path.read_text().splitlines();del lines[0];path.write_text('\n'.join(lines)+'\n')
        rejected=tmp/'must-not-be-exported'
        bad=subprocess.run([sys.executable,'-m','examples.nasuraya_body_loop.resume_continuous_eval',
            str(damaged),str(rejected)],cwd=ROOT,text=True,capture_output=True)
        if bad.returncode==0 or 'boundary prediction mismatch' not in bad.stderr or rejected.exists():
            raise AssertionError('corrupt training boundary was not rejected before export')
    proof=dict(schema='nasuraya-evaluation-resume-contract/1',
        recovered_missing_heldout_prediction=True,all_compared_results_equal=True,
        compared_fields=list(COMPARE),reused_prefix_cycles=96,new_native_cycles=36,
        corrupt_prefix_rejected_before_execution=True,all_passed=True,
        protocol_sha256=expected['protocol_sha256'],
        entrypoint_sha256=hashlib.sha256((Path(__file__).with_name('resume_continuous_eval.py')).read_bytes()).hexdigest())
    args.proof.write_text(json.dumps(proof,sort_keys=True,indent=2)+'\n')
    print(json.dumps(proof,sort_keys=True),flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
