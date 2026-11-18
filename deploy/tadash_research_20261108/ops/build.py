"""Generate three standalone Bridge v2 jobs. Run from any directory."""
import base64
import hashlib
import json
from pathlib import Path
import zlib

OPS=Path(__file__).resolve().parent
TREE=OPS.parent
FILES=["research.py","neuropelvic.py","valuation.py","continuity.py","evening_run.py"]
sources={n:((OPS if n=="evening_run.py" else TREE)/n).read_bytes().decode("utf-8") for n in FILES}
hashes={n:hashlib.sha256(c.encode()).hexdigest() for n,c in sources.items()}
pack=base64.b85encode(zlib.compress(json.dumps(sources,ensure_ascii=False,separators=(",",":")).encode(),9)).decode()
install=(OPS/"install.template").read_text().replace('"_PACKAGE_"',repr(pack)).replace("_HASHES_",repr(hashes))
report=(OPS/"report.template").read_text()
generated={"research_evening_install":install,"research_evening_status":report.replace("_MODE_","status"),
           "research_evening_science":report.replace("_MODE_","scientific")}
directory=OPS/"jobs"
directory.mkdir(exist_ok=True)
for name,code in generated.items():
    data=code.encode("utf-8")
    compile(code,name,"exec")
    print(name,len(data),hashlib.sha256(data).hexdigest())
    if len(data)>24000:
        raise ValueError("Bridge v2 source byte cap")
    (directory/(name+".py")).write_bytes(data)
