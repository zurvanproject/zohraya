"""Build a reproducible text transport bundle; keeps the recovered 70 files exact."""
import base64
import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "runtimes/tadash_body"


def bundle():
    raw = (NATIVE / "PUBLIC_FILES_SHA256.json").read_bytes()
    manifest = json.loads(raw)
    if hashlib.sha256(raw).hexdigest() != "b3b95a88885d903f638efbc26ed693bf7a211460a5adae6dd9abfa12ac7720ef":
        raise ValueError("native manifest mismatch")
    files = {}
    for name, expected in manifest.items():
        data = (NATIVE / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("native source mismatch")
        files["native/" + name] = data
    for name in ("PUBLIC_FILES_SHA256.json", "IMPORT_PROVENANCE.json"):
        files["native/" + name] = (NATIVE / name).read_bytes()
    for name in ("driver.py", "windows_fcntl.py"):
        files[name] = (ROOT / "deploy/tadash_vps" / name).read_bytes()
    files["tzdata/Asia/Tehran"] = base64.b64decode((ROOT / "deploy/tadash_vps/tehran_tzif.b64").read_bytes(), validate=True)
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}
    files["FILES_SHA256.json"] = (json.dumps(hashes, sort_keys=True, indent=2) + "\n").encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 7, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100600 << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return base64.b64encode(out.getvalue())


if __name__ == "__main__":
    output = ROOT / "deploy/tadash_vps_v01.bundle.b64"
    output.write_bytes(bundle())
    print(json.dumps({"sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                      "bytes": output.stat().st_size}))

