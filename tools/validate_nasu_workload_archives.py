#!/usr/bin/env python3
"""Explicit network integration check of public archives in a temporary tree.

Does not install, execute, or activate any downloaded workload. Intended for
CI and preflight validation, not the production workload directory.
"""
import json
from pathlib import Path
import tempfile

import nasu_workload_sources as sources


def main():
    items=sources.catalog(Path(__file__).with_name('nasu_workload_catalog.json'))
    with tempfile.TemporaryDirectory(prefix='nasu-public-archive-check-') as td:
        home=Path(td).resolve()
        for item in items:
            record=sources.stage(item,home)
            print(json.dumps({'component':item['id'],'verified_files':record['verified_files'],
                              'verified_bytes':record['verified_bytes'],
                              'execution':record['execution']},sort_keys=True),flush=True)
        results=sources.status(items,home)
        if any(row['source']!='verified' for row in results):
            raise RuntimeError('post-stage verification failed')
        print('PUBLIC_ARCHIVES=VERIFIED;COMPONENTS='+str(len(items))+';WORKLOADS_EXECUTED=0',flush=True)


if __name__=='__main__':
    main()
