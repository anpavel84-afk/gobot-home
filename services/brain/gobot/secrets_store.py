"""Project-local Windows DPAPI secret storage. Values are never returned by HTTP."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
SECRET = ROOT / "run/secrets/openai-api-key.dpapi"

class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte))]

def _dpapi(data, decrypt=False):
    if os.name != "nt":
        raise RuntimeError("Windows DPAPI is required on this host")
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    result = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise RuntimeError("DPAPI operation failed")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))

def save_openai_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"sk-[A-Za-z0-9_-]{20,1000}", value.strip()):
        raise ValueError("invalid_key_format")
    protected = _dpapi(value.strip().encode("utf-8"))
    SECRET.parent.mkdir(parents=True, exist_ok=True)
    temporary = SECRET.with_suffix(".tmp")
    temporary.write_bytes(protected)
    temporary.replace(SECRET)

def openai_key_present():
    return SECRET.exists() or bool(os.environ.get("OPENAI_API_KEY"))

def load_openai_key():
    if SECRET.exists():
        return _dpapi(SECRET.read_bytes(), decrypt=True).decode("utf-8")
    return os.environ.get("OPENAI_API_KEY", "")
