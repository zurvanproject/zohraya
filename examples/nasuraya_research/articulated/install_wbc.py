"""Install the authored body into WBC's supported custom-robot registry.

Use --config-dir to keep registration isolated from unrelated user robots.
Subsequent WBC commands must use the same WBC_MJLAB_CONFIG_DIR.
"""
import argparse,json
from pathlib import Path
from .evaluate import upstream_check

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config-dir',type=Path,required=True)
    args=ap.parse_args()
    result=upstream_check(args.config_dir.resolve())
    print(json.dumps(result,indent=2))
    if not all(result['registered_tasks'].values()) or not result['settle_check']['ok']:
        raise SystemExit(1)

if __name__=='__main__':main()
