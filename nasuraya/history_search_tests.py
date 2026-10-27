"""Run synthetic history-search tests with a private verified body runtime."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from examples.nasuraya_body_loop.__main__ import verified_sources, SOURCE, ROOT


def main():
    manifest = verified_sources()
    with tempfile.TemporaryDirectory(prefix='nasuraya-history-fts-test-') as temporary:
        work = Path(temporary)
        for name in manifest:
            target = work / name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(SOURCE/name,target)
        env=dict(PATH=os.defpath,PYTHONPATH=str(work)+os.pathsep+str(ROOT),
                 PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1')
        return subprocess.run([sys.executable,'-S','-m','unittest','nasuraya.test_history_search','-v'],
                              cwd=ROOT,env=env).returncode

if __name__ == '__main__':
    raise SystemExit(main())
