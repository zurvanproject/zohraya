"""Audit retained landing-study evidence without rerunning or filtering failures."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
from .build import ROOT
from .experience_balance import write_json
from .landing_study import read_plan, sha


def audit(folder):
    folder=Path(folder);plan=read_plan(folder)
    rows={};traces={};checks=[]
    for split,key in [('diagnostics','diagnostic_variants'),('holdouts','holdout_variants')]:
        for case in plan[split]:
            for variant in plan[key]:
                stem=case['id']+'--'+variant
                row=json.loads((folder/(stem+'.json')).read_text());rows[stem]=row
                if row.get('execution_error'):
                    checks.append(dict(run=stem,execution_error_retained=True));continue
                r=row['result'];path=folder/(stem+'-trace.json.gz')
                assert sha(path)==row['trace_sha256'],stem
                traces[stem]=json.loads(gzip.decompress(path.read_bytes()))
                speeds=row['final_joint_speeds']
                assert len(speeds)==len({x['dof'] for x in speeds})==61
                assert max(abs(x['speed']) for x in speeds)==r['final_max_generalized_speed']
                assert abs(sum(x['seconds'] for x in r['phase_metrics'].values())-r['simulated_seconds'])<1e-8
                assert abs(sum(x['tilt_integral_deg2_s'] for x in r['phase_metrics'].values())-r['tilt_integral_deg2_s'])<1e-8
                assert abs(r['tilt_rms_deg']**2*r['measured_seconds']-r['tilt_integral_deg2_s'])<1e-8
                checks.append(dict(run=stem,trace_hash=True,all_61_dof_speeds=True,time_integrals=True))
    prefix=[]
    for case in plan['diagnostics']+plan['holdouts']:
        variants=plan['diagnostic_variants'] if case in plan['diagnostics'] else plan['holdout_variants']
        for variant in variants:
            if variant in ('baseline','prior6'):continue
            control='baseline' if variant=='tail0' else 'prior6'
            a=traces.get(case['id']+'--'+control);b=traces.get(case['id']+'--'+variant)
            if a is None or b is None:continue
            def before(rows):
                return [r for r in rows if r['step']<case['steps']-1 or
                    (r['step']==case['steps']-1 and r['phase'] in ('transfer','swing'))]
            assert before(a)==before(b),(case['id'],variant)
            prefix.append(dict(case=case['id'],variant=variant,control=control,identical_before_final_landing=True))
    # All old tracked files are compared to the actual local bytes, including
    # unsuccessful historical evidence and native runtime/model files.
    parent=plan['parent_commit']
    tree=subprocess.check_output(['git','ls-tree','-r','-z',parent],cwd=ROOT).split(b'\0')
    preserved=[]
    for entry in tree:
        if not entry:continue
        meta,name=entry.split(b'\t',1);mode,kind,old_hash=meta.split()
        if kind!=b'blob':continue
        path=ROOT/name.decode();data=path.read_bytes()
        actual=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        assert actual==old_hash.decode(),name.decode()
        preserved.append(name.decode())
    result=dict(protocol_sha256=sha(folder/'protocol.json'),rollout_integrity=checks,
        preterminal_prefix_checks=prefix,unchanged_parent_file_count=len(preserved),
        all_parent_files_byte_identical=True,native_apply_allowed=False)
    write_json(folder/'integrity-audit.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    result=audit(p.parse_args().output)
    print(json.dumps({k:v for k,v in result.items() if k not in ('rollout_integrity','preterminal_prefix_checks')}))
