"""Embed the recorded native frames in a response visualization fragment."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def build(destination):
    raw = (ROOT / 'frames.json').read_text()
    data = json.loads(raw)
    if data['schema'] != 'nasuraya-body-mirror/1':
        raise ValueError('unsupported mirror data')
    template = (ROOT / 'mirror.fragment.html').read_text()
    if template.count('__MIRROR_DATA__') != 1:
        raise ValueError('one data slot required')
    Path(destination).write_text(template.replace('__MIRROR_DATA__', raw.replace('</', '<\\/')))


if __name__ == '__main__':
    p = argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    build(p.parse_args().output)
