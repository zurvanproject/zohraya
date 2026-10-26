"""Guarded local entry point; prints fixed alarm fields, never raw errors."""
import argparse
import json
from pathlib import Path
from sentinel import Sentinel,bounded_json


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--repo-root',default=str(Path(__file__).resolve().parents[2]))
    p.add_argument('--manifest',required=True);p.add_argument('--expected-manifest-sha256',required=True)
    p.add_argument('--cache',required=True);p.add_argument('--alerts',required=True)
    group=p.add_mutually_exclusive_group(required=True);group.add_argument('--request');group.add_argument('--status',action='store_true')
    a=p.parse_args();guard=None
    try:
        guard=Sentinel(a.repo_root,a.manifest,a.expected_manifest_sha256,a.cache,a.alerts)
        if a.status:
            result=guard.status();print(json.dumps(result));return 0 if result['visual_state']=='green' else 2
        try:request=bounded_json(a.request,64*1024)
        except (ValueError,TypeError,OSError,RecursionError):request=None
        result=guard.execute(request)
        if result['allowed']:
            r=result['result'];print(json.dumps(dict(allowed=True,mode=r['mode'],actual_ticks=r['actual_ticks'],receipt_sha256=r['receipt']['sha256'])))
            return 0
        print(json.dumps(result));return 2
    except Exception:
        print(json.dumps(dict(allowed=False,alarm=dict(code='sentinel_unavailable',severity='critical'))));return 3
    finally:
        if guard is not None:guard.close()


if __name__=='__main__':raise SystemExit(main())
