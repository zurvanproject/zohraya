"""Verify included source ancestry and source-pinned native/vendor code."""
import json
import subprocess
from .catalog import ROOT, validate


def verify():
    sources = json.loads((ROOT/'integration/sources.json').read_text())
    heads = [sources['base_main']] + [p['sha'] for p in sources['pull_requests']]
    heads += [p['sha'] for p in sources['additional_capabilities']]
    refresh = sources.get('refresh', {})
    if refresh:
        heads += [refresh['main'], refresh['self_model_sha']]
    for sha in heads:
        subprocess.run(['git','merge-base','--is-ancestor',sha,'HEAD'],cwd=ROOT,check=True)
    for name in refresh.get('preserved_main_files', []):
        original = subprocess.check_output(['git', 'show', refresh['main']+':'+name], cwd=ROOT)
        if (ROOT/name).read_bytes() != original:
            raise ValueError('active research contract changed: ' + name)
    from examples.nasuraya_body_loop.__main__ import verified_sources
    from examples.nasuraya_research.integrity import verify_sources
    native = verified_sources()
    vendor = verify_sources()
    return dict(pull_request_heads=len(sources['pull_requests']), additional_capabilities=len(sources['additional_capabilities']),
                native_source_files=len(native), upstream_blobs=len(vendor['files']),
                entrypoints=len(validate()),
                refresh_heads=2 if refresh else 0,
                preserved_main_files=len(refresh.get('preserved_main_files', [])))


if __name__=='__main__':
    print(json.dumps(verify(),indent=2))
