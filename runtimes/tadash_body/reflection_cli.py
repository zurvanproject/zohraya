"""One explicit local ledger operation; no background service."""
import argparse
import json
from pathlib import Path
from reflection_cycle import ReflectionCycle


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',required=True)
    sub=p.add_subparsers(dest='command',required=True)
    d=sub.add_parser('decide');d.add_argument('--request',required=True)
    f=sub.add_parser('complete');f.add_argument('--id',required=True);f.add_argument('--outcome',required=True)
    sub.add_parser('export')
    a=p.parse_args()
    with ReflectionCycle(a.db) as e:
        if a.command=='decide':result=e.decide(json.loads(Path(a.request).read_text()))
        elif a.command=='complete':
            o=json.loads(Path(a.outcome).read_text())
            result=e.complete(a.id,o['actual_outcome'],verified=o['verified'],evidence=o['evidence'],reason=o['reason'])
        else:result=e.export()
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))


if __name__=='__main__':main()
