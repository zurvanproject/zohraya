"""Explicit local start/resume interface; exits at the persisted grant boundary."""
import argparse
import json
from pathlib import Path

from .monitor import SelfModel
from .embodied_learning import LearningJournal, LearningSession, LIMITS
from .evaluate import fixture, prepare_defaults
from unified_body_v2 import UnifiedBody


def run_authorized(journal):
    """At most twelve ticks; opening again never creates a fresh grant."""
    for _ in range(LIMITS['max_ticks']):
        session=journal.load()
        if len(session.records)==session.contract['max_ticks']:
            break
        q=session.request()
        journal.step(event_id=q['event_id'],expected_head=session.checkpoint()['sha256'])
    return journal.load().self_report()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('start','resume','inspect'))
    p.add_argument('--journal',required=True,type=Path)
    p.add_argument('--model',type=Path)
    p.add_argument('--body',type=Path,help='native UnifiedBody checkpoint; read without modifying the input')
    p.add_argument('--session-id',default='authorized-session')
    p.add_argument('--max-ticks',type=int,default=4)
    p.add_argument('--practice-ticks',type=int,default=0)
    p.add_argument('--duration-s',type=float,default=.1)
    a=p.parse_args()
    if a.command=='start':
        if a.model is None:p.error('start requires an existing --model')
        model=SelfModel(a.model)
        if a.body:
            body=UnifiedBody.restore(json.loads(a.body.read_text()))
        else:
            prepare_defaults();body=fixture(.3)
        session=LearningSession.start(body,model,session_id=a.session_id,
            max_ticks=a.max_ticks,practice_ticks=a.practice_ticks,duration_s=a.duration_s)
        journal=LearningJournal.create(a.journal,session)
    else:
        journal=LearningJournal(a.journal)
    report=journal.load().self_report() if a.command=='inspect' else run_authorized(journal)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
