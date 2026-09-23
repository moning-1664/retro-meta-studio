from __future__ import annotations

import base64
import binascii
import ctypes
import sys
from ctypes import wintypes


class SecretError(RuntimeError):
    pass


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


if sys.platform.startswith("win"):
    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32
    _crypt32.CryptProtectData.argtypes = [ctypes.POINTER(_Blob), wintypes.LPCWSTR,
                                          ctypes.POINTER(_Blob), ctypes.c_void_p,
                                          ctypes.c_void_p, wintypes.DWORD,
                                          ctypes.POINTER(_Blob)]
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p,
                                            ctypes.POINTER(_Blob), ctypes.c_void_p,
                                            ctypes.c_void_p, wintypes.DWORD,
                                            ctypes.POINTER(_Blob)]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p
    _advapi32 = ctypes.windll.advapi32
    _advapi32.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
    _advapi32.CredWriteW.restype = wintypes.BOOL
    _advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                    ctypes.POINTER(ctypes.POINTER(_Credential))]
    _advapi32.CredReadW.restype = wintypes.BOOL
    _advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _advapi32.CredDeleteW.restype = wintypes.BOOL
    _advapi32.CredFree.argtypes = [ctypes.c_void_p]
    _advapi32.CredFree.restype = None


_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_CREDENTIAL_PREFIX = "cred:"
_DPAPI_PREFIX = "dpapi:"
_TARGET_PREFIX = "RetroMetaStudio/"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_CRYPTPROTECT_LOCAL_MACHINE = 0x4


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def protect(value: str) -> str:
    if not value:
        return ""
    if not sys.platform.startswith("win"):
        raise SecretError("이 운영체제에서는 안전한 자격 증명 저장을 지원하지 않습니다.")
    raw = value.encode("utf-8")
    source, keepalive = _blob(raw)
    output = _Blob()
    description = ctypes.c_wchar_p("RetroMeta Studio")
    # Some packaged/automation launches do not load a roaming user profile.
    # Machine-scope DPAPI remains encrypted by Windows and works in those launches.
    flags = _CRYPTPROTECT_UI_FORBIDDEN | _CRYPTPROTECT_LOCAL_MACHINE
    if not _crypt32.CryptProtectData(ctypes.byref(source), description, None,
                                     None, None, flags, ctypes.byref(output)):
        raise SecretError("자격 증명을 보호하지 못했습니다.")
    try:
        encrypted = ctypes.string_at(output.pbData, output.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        _kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))


def unprotect(value: str) -> str:
    if not value:
        return ""
    if not sys.platform.startswith("win"):
        raise SecretError("이 운영체제에서는 안전한 자격 증명 저장을 지원하지 않습니다.")
    try:
        encrypted = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise SecretError("저장된 자격 증명을 읽을 수 없습니다.") from exc
    source, keepalive = _blob(encrypted)
    output = _Blob()
    if not _crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None,
                                       _CRYPTPROTECT_UI_FORBIDDEN,
                                       ctypes.byref(output)):
        raise SecretError("저장된 자격 증명을 해제하지 못했습니다.")
    try:
        return ctypes.string_at(output.pbData, output.cbData).decode("utf-8")
    finally:
        _kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))


def store(name: str, value: str) -> str:
    """Store a secret in the current Windows user's Credential Manager."""
    if not sys.platform.startswith("win"):
        raise SecretError("이 운영체제에서는 안전한 자격 증명 저장을 지원하지 않습니다.")
    target = _TARGET_PREFIX + str(name).strip("/")
    raw = str(value).encode("utf-16-le")
    buffer = ctypes.create_string_buffer(raw)
    credential = _Credential()
    credential.Type = _CRED_TYPE_GENERIC
    credential.TargetName = target
    credential.CredentialBlobSize = len(raw)
    credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = "RetroMetaStudio"
    if not _advapi32.CredWriteW(ctypes.byref(credential), 0):
        return _DPAPI_PREFIX + protect(value)
    return _CREDENTIAL_PREFIX + target


def load(reference: str) -> str:
    """Read a Credential Manager reference, with DPAPI compatibility for old values."""
    if not reference:
        return ""
    if str(reference).startswith(_DPAPI_PREFIX):
        return unprotect(str(reference)[len(_DPAPI_PREFIX):])
    if not str(reference).startswith(_CREDENTIAL_PREFIX):
        return unprotect(reference)
    if not sys.platform.startswith("win"):
        raise SecretError("이 운영체제에서는 안전한 자격 증명 저장을 지원하지 않습니다.")
    target = str(reference)[len(_CREDENTIAL_PREFIX):]
    output = ctypes.POINTER(_Credential)()
    if not _advapi32.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(output)):
        raise SecretError("Windows 자격 증명 관리자에서 저장된 값을 찾지 못했습니다.")
    try:
        credential = output.contents
        raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        return raw.decode("utf-16-le")
    finally:
        _advapi32.CredFree(output)


def delete(reference: str):
    if not reference or not str(reference).startswith(_CREDENTIAL_PREFIX):
        return
    if sys.platform.startswith("win"):
        target = str(reference)[len(_CREDENTIAL_PREFIX):]
        _advapi32.CredDeleteW(target, _CRED_TYPE_GENERIC, 0)
