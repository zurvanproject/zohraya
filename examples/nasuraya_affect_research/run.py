"""Explicit source-verified test/evaluation launcher; no long-running service.

Reuse the existing BodyLoop manifest and copy its runtime to a fresh directory.
Native defaults, synthetic ledgers and body outputs never enter source folders.
Preload the three pinned affect modules before legacy imports so every consumer
uses the same verified modules; no monkeypatch or replacement engine is used.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from examples.nasuraya_body_loop.__main__ import ROOT, SOURCE, verified_sources

BOOTSTRAP = '''
import runpy
import sys
from examples.nasuraya_affect_research.appraisal import native_affect
native_affect()
mode = sys.argv[1]
if mode == 'tests':
    sys.argv = ['unittest',
        'examples.nasuraya_affect_research.test_appraisal',
        'examples.nasuraya_affect_research.test_native', '-v']
    runpy.run_module('unittest', run_name='__main__')
elif mode == 'regression':
    sys.argv = ['unittest', 'examples.nasuraya_research.test_confidence', '-v']
    runpy.run_module('unittest', run_name='__main__')
else:
    sys.argv = ['evaluate']
    runpy.run_module('examples.nasuraya_affect_research.evaluate', run_name='__main__')
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('tests', 'regression', 'evaluate'))
    args = parser.parse_args(argv)
    manifest = verified_sources()
    with tempfile.TemporaryDirectory(prefix='nasuraya-affect-native-') as tmp:
        work = Path(tmp)
        for name in manifest:
            dest = work/name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE/name, dest)
        env = {'PATH': os.defpath, 'PYTHONPATH': str(work)+os.pathsep+str(ROOT),
               'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
        child = subprocess.run([sys.executable, '-S', '-c', BOOTSTRAP, args.mode],
                               cwd=work, env=env, timeout=540)
        # Source verification after execution is also required, including failure.
        if verified_sources() != manifest:
            raise RuntimeError('native source manifest changed during execution')
        return child.returncode


if __name__ == '__main__':
    raise SystemExit(main())
