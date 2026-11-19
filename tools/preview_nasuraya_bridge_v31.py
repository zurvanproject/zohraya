#!/usr/bin/env python3
"""Preview-only, no installation: strengthen the existing Issue #212 bridge.

Pass the actual installed bridge as a regular local file to emit the exact
patched copy + unified diff in the supplied *review directory only*.
It never writes to the source path, GitHub, systemd, memory, or Ollama.
"""
import argparse
import ast
import difflib
import hashlib
from pathlib import Path
import re

VERBS = ("research-start", "research-status", "research-stop")
PINNED_INSTALLED_SHA256 = "a8fdac423d1161bf4209e43f991168df31721cb1529e367d01e2b5c10841dd74"
# 20 actual handlers plus help in the Ubuntu screenshot, not assumed from main.
EXISTING_ACTIONS = {
    "status", "disk", "python", "repo", "sync", "test", "offline",
    "awake-stage", "awake-status", "awake-activate", "workload-stage",
    "workload-status", "workload-import", "workload-data-status",
    "stage0-offline", "v2-audit", "v2-inventory", "v2-sources",
    "agent-status", "agent-probe", "help"
}
RUNNER = "/usr/local/lib/nasuraya/nasu_bridge_research.py"


def patch(text, *, exact_live=False):
    if exact_live and hashlib.sha256(text.encode("utf-8")).hexdigest() != PINNED_INSTALLED_SHA256:
        raise ValueError("installed_sha256_changed_refuse")
    if any(x in text for x in ("nasu_bridge_research", "research-start", "research-status", "research-stop")):
        raise ValueError("already_extended_or_unknown_drift")
    tree = ast.parse(text)
    assignment = [node for node in tree.body if isinstance(node,ast.Assign) and
                  any(isinstance(target,ast.Name) and target.id=="COMMAND_RE" for target in node.targets)]
    if len(assignment)!=1:
        raise ValueError("unknown_command_regex")
    node=assignment[0]
    source_lines=text.splitlines(keepends=True)
    call=node.value
    if (not isinstance(call,ast.Call) or not isinstance(call.func,ast.Attribute) or
        call.func.attr!="compile" or len(call.args)!=2 or
        not isinstance(call.args[0],ast.Constant) or
        not isinstance(call.args[0].value,str)):
        raise ValueError("unknown_regex_shape")
    pattern=call.args[0].value
    prefix,suffix=r"(?m)^\s*nasu-linux:\s*(",r")\s*$"
    if not pattern.startswith(prefix) or not pattern.endswith(suffix):
        raise ValueError("unknown_regex_pattern")
    verbs=pattern[len(prefix):-len(suffix)].split("|")
    if (len(set(verbs))!=len(verbs) or not {"status","help","agent-probe","agent-status"}<=set(verbs) or
        not all(re.fullmatch(r"[a-z][a-z0-9-]*",x) for x in verbs)):
        raise ValueError("unknown_regex_verbs")
    if exact_live and set(verbs) != EXISTING_ACTIONS:
        raise ValueError("live_allowlist_changed_refuse")
    fn=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="dispatch"]
    if len(fn)!=1 or fn[0].args.args[0].arg!="action":
        raise ValueError("unknown_dispatch")
    body=fn[0].body
    if (not isinstance(body[-1],ast.Return) or not isinstance(body[-1].value,ast.Constant)
        or not isinstance(body[-1].value.value,str) or not body[-1].value.value.startswith("Allowed:")):
        raise ValueError("unknown_fallback")
    handled=[]
    for branch in body[:-1]:
        if not isinstance(branch,ast.If) or not isinstance(branch.test,ast.Compare):
            raise ValueError("unknown_dispatch_handler")
        test=branch.test
        if (not isinstance(test.left,ast.Name) or test.left.id!="action" or
            len(test.ops)!=1 or not isinstance(test.ops[0],ast.Eq) or
            len(test.comparators)!=1 or not isinstance(test.comparators[0],ast.Constant)):
            raise ValueError("unknown_dispatch_handler")
        handled.append(test.comparators[0].value)
    if set(handled)!=set(verbs)-{"help"} or len(handled)!=len(set(handled)):
        raise ValueError("regex_dispatch_mismatch")
    if text.count("match = COMMAND_RE.search(body)")!=1:
        raise ValueError("unknown_poll_parser")
    new_pattern=prefix+"|".join(verbs+list(VERBS))+suffix
    # AST line/column spans are byte offsets. Instead use stable whole assignment
    # and fallback *line* replacement only after checking exactly one match.
    old_line=source_lines[node.lineno-1]
    if (not old_line.startswith("COMMAND_RE = re.compile(") or old_line.count("re.compile")!=1 or
        not old_line.endswith(", re.I)\n")):
        raise ValueError("unrecognized_command_assignment")
    source_lines[node.lineno-1]="COMMAND_RE = re.compile("+repr(new_pattern)+", re.I)\n"
    fallback=body[-1]
    fallback_line=source_lines[fallback.lineno-1]
    if not fallback_line.startswith('    return ') or not fallback_line.endswith('\n'):
        raise ValueError("unrecognized_fallback_line")
    source_lines[fallback.lineno-1]='    return '+repr(fallback.value.value+' Research: '+', '.join(VERBS)+'.')+'\n'
    # New handlers use only constant argv to a root-installed, reviewed file.
    handlers="""    # NASURAYA_RESEARCH_BRIDGE_BEGIN: fixed, non-root, bounded CLI only
    if action == 'research-start':
        return command(['/usr/bin/python3', '-B', '/usr/local/lib/nasuraya/nasu_bridge_research.py', 'start'], timeout=30)
    if action == 'research-status':
        return command(['/usr/bin/python3', '-B', '/usr/local/lib/nasuraya/nasu_bridge_research.py', 'status'], timeout=30)
    if action == 'research-stop':
        return command(['/usr/bin/python3', '-B', '/usr/local/lib/nasuraya/nasu_bridge_research.py', 'stop'], timeout=30)
    # NASURAYA_RESEARCH_BRIDGE_END
"""
    source_lines.insert(fallback.lineno-1,handlers)
    # Retain legacy first-line command + explanatory paragraphs, but never
    # treat a quoted/embedded command on later lines as a request.
    out="".join(source_lines).replace("match = COMMAND_RE.search(body)",
            "match = COMMAND_RE.fullmatch(body.split('\\n', 1)[0].strip()) if isinstance(body, str) else None")
    compile(out,"<patched-bridge>","exec")
    # Existing 20 command handlers must remain exactly as before.
    new_tree=ast.parse(out)
    new_dispatch=next(n for n in new_tree.body if isinstance(n,ast.FunctionDef) and n.name=="dispatch")
    original=[ast.get_source_segment(text,n) for n in body[:-1]]
    updated=[ast.get_source_segment(out,n) for n in new_dispatch.body if isinstance(n,ast.If)]
    if original != updated[:len(original)]:
        raise ValueError("existing_dispatch_modified")
    if "subprocess.run(argv" not in out or "if api(\"GET\", \"/user\")" not in out:
        raise ValueError("bridge_missing_auth_or_command_helper")
    return out


def main():
    p=argparse.ArgumentParser()
    p.add_argument("source",help="A readable copy of the already installed bridge, never overwritten")
    p.add_argument("review_dir",help="An empty review output folder")
    args=p.parse_args()
    source=Path(args.source)
    out_dir=Path(args.review_dir)
    if source.is_symlink() or not source.is_file() or source.stat().st_size>200000:
        raise SystemExit("invalid_source")
    if not out_dir.is_absolute() or out_dir.exists():
        raise SystemExit("review_directory_must_be_new_absolute_path")
    before=source.read_text(encoding="utf-8")
    after=patch(before, exact_live=True)
    out_dir.mkdir(mode=0o700,parents=True)
    (out_dir/"bridge.before.py").write_text(before,encoding="utf-8")
    (out_dir/"bridge.after.py").write_text(after,encoding="utf-8")
    diff=''.join(difflib.unified_diff(before.splitlines(keepends=True),after.splitlines(keepends=True),
                                     fromfile="bridge.before.py",tofile="bridge.after.py"))
    (out_dir/"bridge.exact.diff").write_text(diff,encoding="utf-8")
    print("PREVIEW_ONLY",hashlib.sha256(before.encode()).hexdigest(),
          hashlib.sha256(after.encode()).hexdigest(),str(out_dir/"bridge.exact.diff"))

if __name__=="__main__":
    main()
