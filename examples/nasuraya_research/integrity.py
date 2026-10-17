"""Verify unmodified, licensed upstream subsets before importing them."""
import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
LOCK_SHA256 = 'db7c4e16ba0a181f9fbbcc837035457f78b06a9631b92863216b7ffe1c9f8e88'


def verify_sources(root=ROOT):
    root = Path(root)
    data = (root / 'upstream-lock.json').read_bytes()
    if hashlib.sha256(data).hexdigest() != LOCK_SHA256:
        raise ValueError('upstream lock changed')
    lock = json.loads(data)
    if lock['schema'] != 'nasuraya-upstream-lock/1' or len(lock['files']) != 9:
        raise ValueError('upstream inventory')
    seen = set()
    for row in lock['files']:
        relative = PurePosixPath(row['local_path'])
        if relative.is_absolute() or '..' in relative.parts or str(relative) in seen:
            raise ValueError('upstream path')
        seen.add(str(relative))
        path = root / str(relative)
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('upstream symlink')
        raw = path.read_bytes()
        git_blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        if (hashlib.sha256(raw).hexdigest() != row['sha256'] or
                git_blob != row['git_blob_sha']):
            raise ValueError('upstream source changed: ' + str(relative))
    return lock
