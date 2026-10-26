"""Run the four arms with fixed Python hashing and enforce identical origin.

--verify-existing checks already-completed arms without executing body ticks.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
CASES=[('star-forward','star','forward',False),
       ('spiral-forward','spiral','forward',False),
       ('spiral-reverse','spiral','reverse',False),
       ('spiral-recovery','spiral','forward',True)]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True)
    p.add_argument('--verify-existing',action='store_true')
    args=p.parse_args()
    output=Path(args.output).resolve()
    if args.verify_existing:
        if not output.is_dir():raise ValueError('missing evidence directory')
    else:
        output.mkdir(parents=True,exist_ok=False)
        env=dict(os.environ,PYTHONHASHSEED='0')
        def child(case):
            name,kind,direction,recovery=case
            command=[sys.executable,str(HERE/'evaluate_spiral.py'),'--kind',kind,
                     '--direction',direction,'--output',str(output/name)]
            if recovery:command.append('--recovery')
            with (output/(name+'.log')).open('w') as log:
                subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(child,CASES))
    # Enforce byte-identical full native origin, not just equal physical stocks.
    origins={name:json.loads((output/name/'initial.json').read_text())['payload']['native']
             for name,*_ in CASES}
    first=origins['star-forward']
    assert all(o==first for o in origins.values()), 'arms do not share one exact native origin'
    from evaluate_spiral import NATIVE
    from verify_spiral import verify
    verified=[verify(output/name) for name,*_ in CASES]
    context=dict(schema='nasuraya-spiral-comparison/1',all_native_origins_exactly_equal=True,
                 initial_native_sha256=first['sha256'],python_hash_seed='0',
                 verified=verified,verification_executed_ticks=0,
                 source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (output/'verification.json').write_text(json.dumps(context,indent=2)+'\n')
    print(json.dumps(context,indent=2))


if __name__=='__main__':main()
