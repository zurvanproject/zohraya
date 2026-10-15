"""Crash-only worker for local deterministic recovery regression."""
import argparse
import os
from pathlib import Path
import sys


def run(args):
    sys.path.insert(0, str(Path(args.native_root).resolve()))
    from motion_journal import MotionJournal
    from persistent_embodiment_v1 import PersistentEmbodiment, atomic_json, digest
    from unified_body_v2 import UnifiedBody
    from coordinated_support import CoordinatedSupport

    journal=MotionJournal(args.journal)
    if args.expected_head and args.event_id:
        expected_head,event_id=args.expected_head,args.event_id
    else:
        goal=journal.load()
        expected_head=goal.checkpoint()['sha256']
        event_id=goal.request()['event_id']
    actual=False
    substeps=0

    def crash(stage, goal=None):
        atomic_json(args.marker, dict(stage=stage,pid=os.getpid(),substeps=substeps,
            task_elapsed=goal.task['elapsed'] if goal else None,
            body_revision=goal.body.revision if goal else None))
        os._exit(86)

    def hook(stage, goal):
        if stage==args.fault:
            crash(stage, goal)

    old_sim=PersistentEmbodiment._simulate
    old_step=CoordinatedSupport.step
    old_cycle=UnifiedBody.cycle

    def simulate(owner,*a,**kw):
        nonlocal actual
        previous=actual
        actual=kw.get('actual',False)
        try:return old_sim(owner,*a,**kw)
        finally:actual=previous

    def step(p,environment):
        nonlocal substeps
        frame=old_step(p,environment)
        if actual:
            substeps+=1
            if args.fault=='mid_native' and substeps==3:
                crash('mid_native')
        return frame

    def cycle(body,**request):
        receipt=old_cycle(body,**request)
        if args.fault=='after_body':
            crash('after_body')
        return receipt

    PersistentEmbodiment._simulate=simulate
    CoordinatedSupport.step=step
    UnifiedBody.cycle=cycle
    receipt=journal.step(event_id=event_id,expected_head=expected_head,hook=hook)
    if args.fault=='none':
        print(digest(receipt))
        return
    raise AssertionError('requested fault was not reached')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--native-root',required=True)
    p.add_argument('--journal',required=True)
    p.add_argument('--marker',required=True)
    p.add_argument('--event-id')
    p.add_argument('--expected-head')
    p.add_argument('--fault',choices=('none','prepared','mid_native','after_body','executed','writing','committed'),required=True)
    run(p.parse_args())
