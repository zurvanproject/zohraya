"""Fixed-origin, TLS-verified Agents API transport with Windows DPAPI credentials."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler

ORIGIN="https://api.openai.com"
ENTROPY=b"NasurayaModelWorker/api-key/v1"


class APIError(RuntimeError):
    def __init__(self,code,status=None):
        self.code=code;self.status=status
        super().__init__(code)


def protected_key(path):
    if os.name!="nt":raise RuntimeError("Windows DPAPI required")
    class Blob(ctypes.Structure):
        _fields_=[("cbData",wintypes.DWORD),("pbData",ctypes.POINTER(ctypes.c_ubyte))]
    raw=Path(path).read_bytes()
    data=(ctypes.c_ubyte*len(raw)).from_buffer_copy(raw)
    entropy=(ctypes.c_ubyte*len(ENTROPY)).from_buffer_copy(ENTROPY)
    incoming=Blob(len(raw),data);extra=Blob(len(ENTROPY),entropy);outgoing=Blob()
    crypt=ctypes.WinDLL("crypt32",use_last_error=True)
    crypt.CryptUnprotectData.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.POINTER(Blob),
                                      ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    crypt.CryptUnprotectData.restype=wintypes.BOOL
    free=ctypes.WinDLL("kernel32",use_last_error=True).LocalFree
    free.argtypes=[ctypes.c_void_p];free.restype=ctypes.c_void_p
    if not crypt.CryptUnprotectData(ctypes.byref(incoming),None,ctypes.byref(extra),None,None,1,ctypes.byref(outgoing)):
        raise APIError("credential_unavailable")
    try:
        value=ctypes.string_at(outgoing.pbData,outgoing.cbData)
        if not re.fullmatch(rb"sk-[A-Za-z0-9_-]{30,}",value):raise APIError("credential_format")
        return value.decode("ascii")
    finally:
        ctypes.memset(outgoing.pbData,0,outgoing.cbData)
        free(outgoing.pbData)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None


class AgentsAPI:
    def __init__(self,key_path,ca_path):
        self.key_path=Path(key_path)
        context=ssl.create_default_context(cafile=str(ca_path))
        self.opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=context))
        self.requests=0

    def request(self,method,path,data=None,idempotency_key=None):
        if method not in ("GET","POST","DELETE") or not re.fullmatch(r"/v1/(?:models|agents/sessions)(?:/[A-Za-z0-9_/-]+)?(?:\?limit=[0-9]+)?",path):
            raise ValueError("fixed API operation required")
        headers={"Authorization":"Bearer "+protected_key(self.key_path),
                 "OpenAI-Beta":"agents=v1","Content-Type":"application/json","User-Agent":"NasurayaServerWorker/1"}
        if idempotency_key:headers["Idempotency-Key"]=idempotency_key
        body=None if data is None else json.dumps(data,separators=(",",":"),allow_nan=False).encode()
        req=Request(ORIGIN+path,data=body,method=method,headers=headers)
        self.requests+=1
        try:
            with self.opener.open(req,timeout=12) as response:
                raw=response.read(1_000_001)
            if len(raw)>1_000_000:raise APIError("response_limit")
            return json.loads(raw) if raw else {}
        except HTTPError as error:
            code="http_error"
            try:
                item=json.loads(error.read(16000)).get("error",{})
                candidate=item.get("code")
                if isinstance(candidate,str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}",candidate):code=candidate
            except Exception:pass
            raise APIError(code,error.code) from None
        except (URLError,TimeoutError,OSError):
            raise APIError("transport_error") from None

