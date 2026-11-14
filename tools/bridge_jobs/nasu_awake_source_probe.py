"""Read-only HTTPS and storage readiness for pinned PR198 offline runtime ZIP."""
import json
import os
import ssl
import sys
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler, HTTPSHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

SHA = "d86750d8d26d4ea6a3fe595f9e1ee81e95d81fec"
TREE = "6ba874c28bd8eec67dde94d6e66b0acc2c87223f"
URLS = (
    "https://codeload.github.com/zurvanproject/zohraya/zip/" + SHA,
    "https://api.github.com/repos/zurvanproject/zohraya/git/trees/" + TREE + "?recursive=1",
)
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def check(url):
    try:
        try:
            import certifi
            context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            context = ssl.create_default_context()
        opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=context))
        req = Request(url, method="HEAD", headers={"User-Agent": "NasurayaPinnedSourceProbe/1"})
        with opener.open(req, timeout=10) as r:
            return str(r.status)
    except (HTTPError, URLError, OSError, ValueError):
        return "ERR"

def main():
    if os.name != "nt":
        return "SOURCE=SKIP_NONWINDOWS"
    if sys.version_info < (3, 11):
        return "SOURCE=BLOCKED;CAUSE=PYTHON"
    a,b = [check(u) for u in URLS]
    if a == "200" and b == "200":
        return "SOURCE=READY;ZIP=200;TREE=200;PY=3."+str(sys.version_info.minor)
    return "SOURCE=BLOCKED;ZIP="+a+";TREE="+b
if __name__ == "__main__":
    try:
        summary = main()
    except BaseException:
        summary = "SOURCE=BLOCKED;CAUSE=UNKNOWN"
    print(json.dumps({"status":"ok","summary":summary}, separators=(",",":")))
