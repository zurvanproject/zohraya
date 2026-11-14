"""Encrypted diagnostics for the one submitted comment; no API writes."""
import base64, hashlib, json, os, zlib
from pathlib import Path
N = 23373001726568783005379464084862010043323679954379322431559007940620622402713796031242417679561396284820508050946974803204781926031493796717919937308895717921264348924565586660963025359880844548715658373408120896497997538015130915307879598493288685712559556123167503408383280581521386432010955084869286246326735580957942237373474862564849728833578703891894514235737842573101595501821890744297091514465649798530481140230788346610466331294884594795769585281008103038337837831382237796939463050724975780012492296077821042144529812002217533352951429580741135865868933592390690195717609838004990199796061769381363755362121
PART = 2
COMMENT = "8501fef0-5b16-4c9d-a58a-9683974d62cf"
def mgf(seed, size):
    return b"".join(hashlib.sha256(seed+i.to_bytes(4,"big")).digest() for i in range((size+31)//32))[:size]
def encrypt(message):
    if len(message)>190: raise ValueError("Too large")
    db=hashlib.sha256(b"").digest()+b"\0"*(190-len(message))+b"\1"+message
    seed=os.urandom(32)
    masked_db=bytes(a^b for a,b in zip(db,mgf(seed,223)))
    masked_seed=bytes(a^b for a,b in zip(seed,mgf(masked_db,32)))
    encoded=b"\0"+masked_seed+masked_db
    return pow(int.from_bytes(encoded,"big"),65537,N).to_bytes(256,"big")
def main():
    try:
        root=Path(os.environ["LOCALAPPDATA"])/"Nasuraya"/"Moltbook"
        data=json.loads((root/"first_reply.json").read_text(encoding="utf-8"))
        if data.get("comment_id") != COMMENT: raise ValueError("Wrong comment")
        verification=data.get("verification") or {}
        challenge=verification.get("challenge_text")
        if not isinstance(challenge,str):
            summary="NO_CHALLENGE"
        else:
            p=root/"first_reply_challenge.rsa"
            if not p.exists():
                p.write_text(base64.b64encode(encrypt(zlib.compress(challenge.encode("utf-8")))).decode("ascii"),encoding="ascii")
            cipher=p.read_text(encoding="ascii")
            summary="C"+str(PART)+"="+cipher[(PART-1)*172:PART*172]
    except Exception:
        summary="DIAGNOSTIC_UNAVAILABLE"
    print(json.dumps({"status":"ok","summary":summary},separators=(",",":")))
if __name__=="__main__": main()
