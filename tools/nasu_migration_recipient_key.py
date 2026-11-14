"""Create an Ubuntu-only RSA OAEP recipient key and publish only its public XML."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path('/var/lib/nasuraya/migration')
KEY = ROOT / 'recipient-private.pem'

def item(data, offset, tag):
    if data[offset] != tag:
        raise ValueError('Unexpected RSA DER type')
    offset += 1
    size = data[offset]
    offset += 1
    if size & 0x80:
        count = size & 0x7f
        size = int.from_bytes(data[offset:offset+count], 'big')
        offset += count
    return data[offset:offset+size], offset+size

def public_xml(der):
    sequence, pos = item(der, 0, 0x30)
    if pos != len(der):
        raise ValueError('Unexpected extra DER bytes')
    modulus, pos = item(sequence, 0, 0x02)
    exponent, pos = item(sequence, pos, 0x02)
    if pos != len(sequence):
        raise ValueError('Unexpected RSA DER fields')
    modulus = modulus.lstrip(b'\0')
    exponent = exponent.lstrip(b'\0')
    if len(modulus) != 384 or exponent != b'\x01\x00\x01':
        raise ValueError('Unexpected RSA key strength')
    b64 = lambda v: base64.b64encode(v).decode('ascii')
    return '<RSAKeyValue><Modulus>'+b64(modulus)+'</Modulus><Exponent>'+b64(exponent)+'</Exponent></RSAKeyValue>'

def main():
    if os.geteuid() == 0:
        raise RuntimeError('Refusing root')
    os.umask(0o077)
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not KEY.exists():
        tmp = ROOT / 'recipient-new.tmp'
        if tmp.exists():
            raise RuntimeError('Existing unreviewed key staging file')
        try:
            subprocess.run(['/usr/bin/openssl','genpkey','-algorithm','RSA',
                '-pkeyopt','rsa_keygen_bits:3072','-out',str(tmp)],
                check=True,timeout=60,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            tmp.chmod(0o600)
            tmp.replace(KEY)
        finally:
            if tmp.exists():
                tmp.unlink()
    if KEY.is_symlink():
        raise RuntimeError('Recipient key must not be a symlink')
    der = subprocess.check_output(['/usr/bin/openssl','rsa','-in',str(KEY),
        '-RSAPublicKey_out','-outform','DER'], timeout=10,stderr=subprocess.DEVNULL)
    xml = public_xml(der)
    print(json.dumps({'schema':'nasuraya-migration-recipient/1','public_xml':xml,
          'fingerprint_sha256':hashlib.sha256(der).hexdigest()},separators=(',',':')))

if __name__ == '__main__':
    main()
