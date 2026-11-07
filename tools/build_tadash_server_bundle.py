from pathlib import Path
import base64,hashlib,io,json,zipfile
root=Path(__file__).resolve().parents[1]
source=root/"deploy/tadash_server"
names=["worker.py","api.py","native_tools.py","cacert.pem","CERTIFI_LICENSE"]
files={n:(source/n).read_bytes() for n in names}
manifest=json.dumps({n:hashlib.sha256(v).hexdigest() for n,v in sorted(files.items())},sort_keys=True,separators=(",",":")).encode()
files["FILES_SHA256.json"]=manifest
data=io.BytesIO()
with zipfile.ZipFile(data,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
 for name,raw in sorted(files.items()):
  entry=zipfile.ZipInfo(name,(2026,11,7,0,0,0));entry.external_attr=0o100600<<16;entry.compress_type=zipfile.ZIP_DEFLATED
  z.writestr(entry,raw)
payload=base64.b64encode(data.getvalue())
(root/"deploy/tadash_server_v01.bundle.b64").write_bytes(payload)
print(json.dumps({"package_sha256":hashlib.sha256(payload).hexdigest(),"manifest_sha256":hashlib.sha256(manifest).hexdigest(),"bytes":len(payload)}))
