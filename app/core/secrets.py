from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes
from pathlib import Path


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


class SecretProtector:
    """DPAPI on Windows; private-file fallback supports future non-Windows runtimes."""

    def protect(self, value: str) -> str:
        raw=value.encode("utf-8")
        if os.name!="nt":return "plain:"+base64.b64encode(raw).decode("ascii")
        source,keep=_blob(raw);output=_DataBlob()
        if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source),"Tinix",None,None,None,0,ctypes.byref(output)):
            raise OSError("DPAPI CryptProtectData failed")
        try:data=ctypes.string_at(output.pbData,output.cbData)
        finally:ctypes.windll.kernel32.LocalFree(output.pbData)
        return "dpapi:"+base64.b64encode(data).decode("ascii")

    def unprotect(self, value: str) -> str:
        prefix,encoded=value.split(":",1);raw=base64.b64decode(encoded)
        if prefix=="plain":return raw.decode("utf-8")
        if prefix!="dpapi" or os.name!="nt":raise ValueError("Protected secret không tương thích host.")
        source,keep=_blob(raw);output=_DataBlob()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source),None,None,None,None,0,ctypes.byref(output)):
            raise OSError("DPAPI CryptUnprotectData failed")
        try:data=ctypes.string_at(output.pbData,output.cbData)
        finally:ctypes.windll.kernel32.LocalFree(output.pbData)
        return data.decode("utf-8")

    def protect_oauth(self, value: str) -> str:
        if os.name != "nt":
            raise RuntimeError("OAuth token storage yêu cầu encrypted host storage; plaintext fallback bị từ chối.")
        return self.protect(value)

    def protect_secret(self, value: str) -> str:
        if os.name != "nt":
            raise RuntimeError("Credential storage yêu cầu Windows DPAPI; plaintext fallback bị từ chối.")
        return self.protect(value)

    def unprotect_oauth(self, value: str) -> str:
        if not value.startswith("dpapi:"):
            raise ValueError("OAuth secret không được mã hóa bằng host protection.")
        return self.unprotect(value)

    def unprotect_secret(self, value: str) -> str:
        if not value.startswith("dpapi:"):
            raise ValueError("Credential không được mã hóa bằng host protection.")
        return self.unprotect(value)

    def write_file(self,path:Path,value:str)->None:
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(self.protect(value),encoding="utf-8")
        if os.name!="nt":path.chmod(0o600)

    def read_file(self,path:Path)->str:return self.unprotect(path.read_text(encoding="utf-8"))
