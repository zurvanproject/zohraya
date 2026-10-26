"""Two synthetic caller messages, separate processes, persistent mechanical state.

Publishes only mechanical measurements and aggregate checks, never dialogue or
SQLite/affective records. Temporary sessions are private and discarded.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from .engine import digest

ROOT=Path(__file__).resolve().parents[2]


def evaluate(output):
    output.mkdir(parents=True,exist_ok=True)
    env=dict(PATH=os.defpath,PYTHONPATH=str(ROOT),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',
             PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1')
    with tempfile.TemporaryDirectory(prefix='articulated-v02-') as folder:
        folder=Path(folder);session=folder/'session'
        def cli(*args):
            run=subprocess.run([sys.executable,'-m','examples.nasuraya_affect.articulated_cli',*args,
                                '--session-dir',str(session)],env=env,cwd=ROOT,capture_output=True,text=True,timeout=180)
            if run.returncode:
                raise RuntimeError(run.stderr)
            return json.loads(run.stdout)
        cli('init','--max-trials','2')
        template=json.loads((ROOT/'examples/nasuraya_affect/articulated-example.json').read_text())
        template['steps']=1
        receipts=[]
        for index in (1,2):
            message=dict(template,id=f'synthetic-bout-{index}')
            path=folder/f'message-{index}.json';path.write_text(json.dumps(message))
            receipts.append(cli('message','--message',str(path)))
        a,b=[r['measurement'] for r in receipts]
        assert a['walk_pass'] and b['walk_pass']
        assert a['accepted_steps']==b['accepted_steps']==1
        assert b['initial_qpos']==a['final_qpos'] and b['initial_qvel']==a['final_qvel']
        assert b['start_time']==a['end_time'] and b['initialization_seconds']==0
        assert b['initial_integration_sha256']==digest(a['checkpoint']['value']['integration'])
        assert [a['steps'][0]['swing_side'],b['steps'][0]['swing_side']]==[0,1]
        # Reopen yet again. Replaying the OLD message must not rewind current body
        # or affect. A fresh motion request must remain blocked by spent budget.
        verify='''import json,sys
from pathlib import Path
from examples.nasuraya_affect.engine import AffectiveAgent
from examples.nasuraya_affect.articulated_dialogue import ArticulatedDialogue,Blocked
from examples.nasuraya_affect import articulated_dialogue as m
def forbidden(*a,**k):raise AssertionError('no simulation allowed')
m.execute_trial=forbidden
folder=Path(sys.argv[1])
with AffectiveAgent(folder/'session/affect.sqlite') as agent:
 bridge=ArticulatedDialogue(agent);before=bridge.status();state=agent.state()
 old=json.loads((folder/'message-1.json').read_text())
 r=bridge.receive(old)
 assert r['replayed'] and r['this_call_trials']==0
 assert bridge.status()==before and agent.state()==state
 old['id']='third-bout'
 try:bridge.receive(old)
 except Blocked:pass
 else:raise AssertionError('budget bypass')
 print(json.dumps(dict(old_replay_preserves_latest_body=True,memory_unchanged=True,simulation_forbidden=True,third_bout_blocked=True)))
'''
        verified=subprocess.run([sys.executable,'-c',verify,str(folder)],env=env,cwd=ROOT,
                                capture_output=True,text=True,timeout=30)
        if verified.returncode:raise RuntimeError(verified.stderr)
        proof=json.loads(verified.stdout)
        summary=dict(scope='Two one-step synthetic messages in separate processes; stopped and settled between bouts.',
            bouts=[{k:r[k] for k in ('accepted_steps','walk_pass','initialization_seconds','start_time','end_time',
                  'max_tilt_deg','max_joint_limit_excess_rad','max_motor_torque_fraction','nonfoot_ground_contacts',
                  'pelvis_displacement_xyz_m','initial_integration_sha256','continued_from')} for r in (a,b)],
            exact_boundary_position_velocity_time=True,exact_integration_state_restored=True,
            alternating_swing_sides=[0,1],replay=proof,
            total_simulated_seconds=b['end_time'],final_checkpoint_sha256=b['checkpoint']['sha256'])
        (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        (output/'mechanical-bouts.json').write_text(json.dumps([a,b],separators=(',',':'))+'\n')
        return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(evaluate(args.output),indent=2))
