"""Download public, revision-pinned model data and verify every file digest."""
import argparse
import json
import os
from pathlib import Path
import urllib.request

from .data import sha


def download(output):
    source = json.loads(Path(__file__).with_name('model-source.json').read_text())
    out = Path(output).resolve()
    out.mkdir(parents=True,exist_ok=True)
    for name, expected in source['files_sha256'].items():
        dest = out/name
        if dest.exists():
            if sha(dest) != expected:
                raise ValueError('existing base file differs: '+name)
            continue
        url = f'https://huggingface.co/{source["model"]}/resolve/{source["revision"]}/{name}'
        part = out/(name+'.part')
        with urllib.request.urlopen(url,timeout=60) as response,part.open('wb') as stream:
            for chunk in iter(lambda:response.read(1024*1024),b''):
                stream.write(chunk)
        if sha(part) != expected:
            raise ValueError('download checksum mismatch: '+name)
        os.replace(part,dest)
        print(json.dumps(dict(downloaded=name,sha256=expected)),flush=True)


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    download(parser.parse_args().output)
