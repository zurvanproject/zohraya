"""Actual native recovery fixtures; timer comparator is never a runtime option."""
import json
from pathlib import Path

from .session import Session
from .adapters import native_call
from .__main__ import demo_frames, write
from .reconsider import observation


def run(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    results={}
    for fixture in ('transient_pain','sleep'):
        results[fixture]={}
        for policy,enabled in (('permanent_veto',False),('evidence_bound',True)):
            path=directory/(fixture+'-'+policy)
            session=Session.create(path,backend='native',fixture=fixture,
                                   reconsideration=enabled,max_actions=8)
            initial=session.snapshot();receipts=[];restarts=[]
            try:
                for index in range(8):
                    if index==3:
                        before=session.snapshot();session.close();session=Session(path)
                        restarts.append(before==session.snapshot())
                    receipt=session.step('e'+str(index),demo_frames(index,0),expected_revision=index)
                    receipts.append(dict(receipt,body_indices=session.snapshot()['body']['export']['minimum_state']))
                final=session.snapshot()
                session.stop()
            finally:session.close()
            results[fixture][policy]={'receipts':receipts,'restart_equal':all(restarts),
                'initial_body':initial['body']['export'],'final_body':final['body']['export'],
                'final_walk_evidence':final['dios']['action_reviews']['walk']['evidence_review'],
                'walks':sum(r['outcome']['executed']=='walk' for r in receipts),
                'vetoed_walks':sum(r['requested']=='walk' and r['outcome']['executed']!='walk' for r in receipts),
                'actions_used':final['actions_used'],'source_identity':final['source_identity']}
        # Research-only timer: one observe after a veto, then walk again. It uses
        # the same native fixture/inputs/duration but has no recovery evidence gate.
        native=native_call({'checkpoint':None,'fixture':fixture})
        cooldown=0;receipts=[]
        for index in range(8):
            requested='observe' if index==0 or cooldown else 'walk'
            cooldown=max(0,cooldown-1)
            # Quiet afferents still have the same engineering noise as the actor.
            from examples.tadash_interoception.state import InternalState
            if index==0:state=InternalState()
            for frame in demo_frames(index,0):state.step(frame)
            native=native_call({'checkpoint':native['checkpoint'],'fixture':fixture,'duration':1.6,
                'touch':min(1.,max(state.features())),'event_id':'timer-'+str(index),'requested':requested})
            receipt=native['receipt'];receipts.append(dict(receipt,indices=observation(native)['values']))
            if requested=='walk' and receipt['executed']!='walk':cooldown=1
        results[fixture]['timer_only_research']={'receipts':receipts,
            'walks':sum(r['executed']=='walk' for r in receipts),
            'vetoed_walks':sum(r['requested']=='walk' and r['executed']!='walk' for r in receipts),
            'runtime_policy_available':False}
    write(directory/'result.json',results)
    return results


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();run(args.output);print(json.dumps({'result':str(args.output/'result.json')}))
