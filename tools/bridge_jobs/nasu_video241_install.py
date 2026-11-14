"""Pinned, isolated FFmpeg assembly tool for the legacy Windows video worker.

No system PATH changes, pip install, background process, model download, or paid API.
Bridge v2 downloads this standalone source by commit and checks its SHA256.
"""
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time
import urllib.request
import zipfile

WHEEL_URL = ('https://files.pythonhosted.org/packages/c6/01/'
             '716106099e48c4f419876d5814679a94dd7d6f441217c97c1b608123c6bb/'
             'imageio_ffmpeg-0.4.9-py3-none-win_amd64.whl')
WHEEL_SHA256 = '7e900c695c6541b1cb17feb1baacd4009b30a53a45b81c23d53a67ab13ffb766'
WHEEL_BYTES = 22619540
EXE_MEMBER = 'imageio_ffmpeg/binaries/ffmpeg-win64-v4.2.2.exe'
EXE_SHA256 = '404fdd541eecc577d8f24bf9a976f1e4209f4292022a41c01f5cc2f1b0d375ac'
EXE_BYTES = 64654336
LICENSE_MEMBER = 'imageio_ffmpeg-0.4.9.dist-info/LICENSE'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def download(opener=urllib.request.urlopen):
    deadline = time.monotonic() + 28
    chunks, size = [], 0
    with opener(WHEEL_URL, timeout=8) as response:
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError('download deadline')
            chunk = response.read(131072)
            if not chunk:
                break
            size += len(chunk)
            if size > WHEEL_BYTES:
                raise ValueError('oversized wheel')
            chunks.append(chunk)
    data = b''.join(chunks)
    if len(data) != WHEEL_BYTES or digest(data) != WHEEL_SHA256:
        raise ValueError('wheel verification failed')
    return data


def extract_verified(data):
    # Never extract archive paths. Read only exact allowlisted members.
    if len(data) != WHEEL_BYTES or digest(data) != WHEEL_SHA256:
        raise ValueError('wheel verification failed')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        info = archive.getinfo(EXE_MEMBER)
        if info.file_size != EXE_BYTES:
            raise ValueError('binary size mismatch')
        binary = archive.read(EXE_MEMBER)
        if digest(binary) != EXE_SHA256:
            raise ValueError('binary verification failed')
        license_info = archive.getinfo(LICENSE_MEMBER)
        if license_info.file_size > 65536:
            raise ValueError('oversized license')
        license_data = archive.read(LICENSE_MEMBER)
    return binary, license_data


def atomic_write(path, data):
    tmp = path.with_suffix(path.suffix + '.partial')
    tmp.write_bytes(data)
    os.replace(tmp, path)


def ensure_binary(root, fetch=download):
    exe = root / 'ffmpeg.exe'
    if exe.exists() and exe.stat().st_size == EXE_BYTES and digest(exe.read_bytes()) == EXE_SHA256:
        return exe
    binary, license_data = extract_verified(fetch())
    atomic_write(root / 'imageio-ffmpeg-LICENSE.txt', license_data)
    atomic_write(exe, binary)
    return exe


def run_checked(args, timeout=8):
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          timeout=timeout, stdin=subprocess.DEVNULL).stdout


def smoke(exe, root):
    version = run_checked([str(exe), '-version']).splitlines()[0]
    if not version.startswith('ffmpeg version 4.2.2'):
        raise ValueError('unexpected FFmpeg version')
    output = root / 'video241-smoke.mp4'
    run_checked([str(exe), '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                 '-f', 'lavfi', '-i', 'color=c=0x2b1724:s=320x240:r=12:d=1',
                 '-threads', '1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                 '-movflags', '+faststart', str(output)])
    if not output.exists() or output.stat().st_size < 512:
        raise ValueError('missing smoke output')
    run_checked([str(exe), '-nostdin', '-hide_banner', '-loglevel', 'error',
                 '-i', str(output), '-f', 'null', '-'])
    return version, output.stat().st_size


def ram_mib():
    class MemoryStatus(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong) for name in
            ('total_phys', 'avail_phys', 'total_page', 'avail_page',
             'total_virtual', 'avail_virtual', 'extended')]
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return 0
    return status.total_phys // (1024 * 1024)


def gpu_vram_mib():
    # An unknown result is not evidence that no GPU exists.
    smi = shutil.which('nvidia-smi')
    if not smi:
        return None
    try:
        out = run_checked([smi, '--query-gpu=memory.total', '--format=csv,noheader,nounits'], 4)
        return [int(line.strip()) for line in out.splitlines() if line.strip().isdigit()]
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def install():
    if platform.system() != 'Windows' or platform.machine().lower() not in ('amd64', 'x86_64'):
        return {'status': 'ok', 'summary': 'VIDEO241=SKIPPED;REASON=WINDOWS_X64_REQUIRED'}
    root = Path(os.environ['PROGRAMDATA']) / 'NasurayaBridge' / 'video241_v1'
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < 200 * 1024 * 1024:
        raise OSError('insufficient scratch space')
    exe = ensure_binary(root)
    version, size = smoke(exe, root)
    gpu = gpu_vram_mib()
    receipt = {'installed': True, 'utc_epoch': int(time.time()), 'tool': version,
               'binary_sha256': EXE_SHA256, 'wheel_sha256': WHEEL_SHA256,
               'smoke_encoded_and_decoded': True, 'smoke_bytes': size,
               'cpu_count': os.cpu_count(), 'ram_mib': ram_mib(), 'gpu_vram_mib': gpu,
               'role': 'video encoding and assembly; no generative model installed'}
    atomic_write(root / 'receipt.json', json.dumps(receipt, indent=2).encode('ascii'))
    gpu_text = 'UNKNOWN' if gpu is None else ','.join(map(str, gpu)) or 'NONE'
    return {'status': 'ok', 'summary':
            'VIDEO241=INSTALLED;FFMPEG=4.2.2;ENCODE=OK;DECODE=OK;CPU=%s;RAM_MIB=%s;VRAM_MIB=%s' %
            (receipt['cpu_count'], receipt['ram_mib'], gpu_text)}


if __name__ == '__main__':
    try:
        result = install()
    except Exception as error:
        # Deliberately do not publish paths, command output, or environment values.
        result = {'status': 'ok', 'summary': 'VIDEO241=FAILED;ERROR=' + type(error).__name__}
    print(json.dumps(result, separators=(',', ':')))
