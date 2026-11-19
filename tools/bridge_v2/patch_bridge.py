#!/usr/bin/env python3
"""Append only three fixed commands to the deployed bridge, preserving old verbs."""
import ast
from pathlib import Path
import re
import sys

VERBS = ('v2-audit', 'v2-inventory', 'v2-sources')
WORKER = '/usr/local/lib/nasuraya/bridge_v2/worker.py'


def patch(text):
    if any(f'if action == "{v}"' in text for v in VERBS):
        raise RuntimeError('ALREADY_PATCHED')
    m = re.search(r'(?m)^COMMAND_RE = re\.compile\(r"([^"\n]+)", re\.I\)\s*$', text)
    if not m:
        raise RuntimeError('COMMAND_RE_UNRECOGNIZED')
    prefix = r'(?m)^\s*nasu-linux:\s*('
    suffix = r')\s*$'
    regex = m.group(1)
    if not regex.startswith(prefix) or not regex.endswith(suffix):
        raise RuntimeError('COMMAND_RE_CHANGED')
    words = regex[len(prefix):-len(suffix)].split('|')
    if not {'status', 'repo', 'awake-status', 'help', 'stage0-offline'}.issubset(words):
        raise RuntimeError('REQUIRES_STAGE0_DEPLOYED')
    if any(not re.fullmatch(r'[a-z][a-z0-9-]*', w) for w in words):
        raise RuntimeError('UNEXPECTED_COMMAND_PATTERN')
    new_words = [w for w in words if w != 'help'] + list(VERBS) + ['help']
    text = text[:m.start(1)] + prefix + '|'.join(new_words) + suffix + text[m.end(1):]
    marker = 'def dispatch(action):\n'
    if text.count(marker) != 1:
        raise RuntimeError('DISPATCH_CHANGED')
    additions = ''.join(
        f'    if action == "{verb}":\n'
        f'        return command(["/usr/bin/python3", "-I", "-B", "{WORKER}", "{action}"], timeout={timeout})\n'
        for verb, action, timeout in [('v2-audit', 'audit', 20), ('v2-inventory', 'inventory', 20),
                                      ('v2-sources', 'sources', 110)]
    )
    text = text.replace(marker, marker + additions, 1)
    h = re.search(r'(?m)^(\s*return "Allowed: )([^"\n]+)(\. No arbitrary shell\.\")', text)
    if not h or 'help' not in h.group(2):
        raise RuntimeError('HELP_TEXT_CHANGED')
    help_text = h.group(2).replace('help', ', '.join(VERBS) + ', help', 1)
    text = text[:h.start(2)] + help_text + text[h.end(2):]
    ast.parse(text)
    return text


def main(args):
    if len(args) != 2:
        raise RuntimeError('USAGE: patch_bridge.py input.py output.py')
    src, dst = [Path(x) for x in args]
    if src.is_symlink() or not src.is_file() or dst.exists() or dst.is_symlink():
        raise RuntimeError('UNSAFE_SOURCE_OR_DESTINATION')
    dst.write_text(patch(src.read_text(encoding='utf-8')), encoding='utf-8')
    print('BRIDGE_V2_PATCH_PREPARED;ONLY=v2-audit,v2-inventory,v2-sources')


if __name__ == '__main__':
    main(sys.argv[1:])
