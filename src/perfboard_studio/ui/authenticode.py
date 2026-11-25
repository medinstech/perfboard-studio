"""Who signed a file, as Windows sees it: ``WinVerifyTrust`` through ``ctypes``.

Read once, at the moment Install and Restart is clicked, on the installer about to be run
(``updater.start_install``). Nothing imports this module at start-up: ``ctypes`` and the
two DLLs are loaded on that click and not before.

WHY ``WinVerifyTrust`` AND NOT ``Get-AuthenticodeSignature``. The cmdlet is the same call
underneath, reached by starting a PowerShell -- half a second on a warm machine, longer on a
cold one, and a process this program would start with whatever ``PATH``, profile and
language mode the machine has. ``updater.py`` also starts no process but the installer, and
a test reads the source to keep it so. Asking the DLL directly costs a few milliseconds and
answers the same question with the same policy (``WINTRUST_ACTION_GENERIC_VERIFY_V2``,
what Explorer's Digital Signatures tab and the elevation prompt use).

WHAT IS ASKED. That the signature is intact over the file's bytes and chains to a root this
machine trusts -- a timestamped signature stays valid after its certificate expires, as
Windows treats it everywhere else -- and then, from the same verification's state, the
signer certificate's common name and SHA-1 thumbprint. Whether that signer is this
project's publisher is ``updates.signature_verdict``, which needs no Windows to be tested.

REVOCATION IS NOT CHECKED HERE. Checking it means fetching the CA's list over the network
from inside a click, and a CA's server that is down would stop every update; the elevation
prompt Windows shows next does its own check with its own cache. The hash taken just before
(``SHA256SUMS``) and the pinned publisher are what this check adds.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

#: ``WinVerifyTrust`` result when this is not Windows; outside every real HRESULT.
NOT_WINDOWS = 0xFFFFFFFF


@dataclass(frozen=True, slots=True)
class Signature:
    """``WinVerifyTrust``'s answer as an unsigned HRESULT (0 = intact and trusted), and the
    signer's certificate when it was."""

    status: int
    common_name: str = ""
    thumbprint: str = ""


class _Guid(ctypes.Structure):
    _fields_ = (
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    )


class _FileInfo(ctypes.Structure):
    _fields_ = (
        ("cbStruct", wintypes.DWORD),
        ("pcwszFilePath", wintypes.LPCWSTR),
        ("hFile", wintypes.HANDLE),
        ("pgKnownSubject", ctypes.POINTER(_Guid)),
    )


class _TrustData(ctypes.Structure):
    _fields_ = (
        ("cbStruct", wintypes.DWORD),
        ("pPolicyCallbackData", ctypes.c_void_p),
        ("pSIPClientData", ctypes.c_void_p),
        ("dwUIChoice", wintypes.DWORD),
        ("fdwRevocationChecks", wintypes.DWORD),
        ("dwUnionChoice", wintypes.DWORD),
        ("pFile", ctypes.POINTER(_FileInfo)),
        ("dwStateAction", wintypes.DWORD),
        ("hWVTStateData", wintypes.HANDLE),
        ("pwszURLReference", wintypes.LPWSTR),
        ("dwProvFlags", wintypes.DWORD),
        ("dwUIContext", wintypes.DWORD),
        ("pSignatureSettings", ctypes.c_void_p),
    )


class _ProviderCert(ctypes.Structure):
    # Only the head of CRYPT_PROVIDER_CERT: this reads it through a pointer Windows owns.
    _fields_ = (("cbStruct", wintypes.DWORD), ("pCert", ctypes.c_void_p))


_WTD_UI_NONE = 2
_WTD_REVOKE_NONE = 0
_WTD_CHOICE_FILE = 1
_WTD_STATEACTION_VERIFY = 1
_WTD_STATEACTION_CLOSE = 2
_WTD_REVOCATION_CHECK_NONE = 0x10
_CERT_NAME_ATTR_TYPE = 3
_OID_COMMON_NAME = b"2.5.4.3"
_CERT_SHA1_HASH_PROP_ID = 3


def _generic_verify_v2() -> _Guid:
    """WINTRUST_ACTION_GENERIC_VERIFY_V2, {00AAC56B-CD44-11d0-8CC2-00C04FC295EE}."""
    tail = (ctypes.c_ubyte * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE)
    return _Guid(0x00AAC56B, 0xCD44, 0x11D0, tail)


def _signer(wintrust: Any, crypt32: Any, state: int) -> tuple[str, str]:
    """The signer certificate's common name and thumbprint, from a verification's state."""
    wintrust.WTHelperProvDataFromStateData.restype = ctypes.c_void_p
    wintrust.WTHelperProvDataFromStateData.argtypes = (wintypes.HANDLE,)
    wintrust.WTHelperGetProvSignerFromChain.restype = ctypes.c_void_p
    wintrust.WTHelperGetProvSignerFromChain.argtypes = (
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    )
    wintrust.WTHelperGetProvCertFromChain.restype = ctypes.POINTER(_ProviderCert)
    wintrust.WTHelperGetProvCertFromChain.argtypes = (ctypes.c_void_p, wintypes.DWORD)
    crypt32.CertGetNameStringW.restype = wintypes.DWORD
    crypt32.CertGetNameStringW.argtypes = (
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPWSTR,
        wintypes.DWORD,
    )
    crypt32.CertGetCertificateContextProperty.restype = wintypes.BOOL
    crypt32.CertGetCertificateContextProperty.argtypes = (
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
    )

    provider = wintrust.WTHelperProvDataFromStateData(state)
    if not provider:
        return "", ""
    signer = wintrust.WTHelperGetProvSignerFromChain(provider, 0, False, 0)
    if not signer:
        return "", ""
    cert = wintrust.WTHelperGetProvCertFromChain(signer, 0)
    if not cert or not cert.contents.pCert:
        return "", ""
    context = cert.contents.pCert

    oid = ctypes.c_char_p(_OID_COMMON_NAME)
    oid_pointer = ctypes.cast(oid, ctypes.c_void_p)
    length = crypt32.CertGetNameStringW(context, _CERT_NAME_ATTR_TYPE, 0, oid_pointer, None, 0)
    name = ctypes.create_unicode_buffer(max(length, 1))
    crypt32.CertGetNameStringW(context, _CERT_NAME_ATTR_TYPE, 0, oid_pointer, name, length)

    size = wintypes.DWORD(0)
    thumbprint = ""
    if crypt32.CertGetCertificateContextProperty(
        context, _CERT_SHA1_HASH_PROP_ID, None, ctypes.byref(size)
    ):
        digest = (ctypes.c_ubyte * size.value)()
        if crypt32.CertGetCertificateContextProperty(
            context, _CERT_SHA1_HASH_PROP_ID, digest, ctypes.byref(size)
        ):
            thumbprint = bytes(digest).hex().upper()
    return name.value, thumbprint


def read_signature(path: str) -> Signature:
    """Verify ``path``'s Authenticode signature and say who made it. Never raises."""
    if sys.platform != "win32":
        return Signature(NOT_WINDOWS)
    wintrust = ctypes.WinDLL("wintrust")
    crypt32 = ctypes.WinDLL("crypt32")
    wintrust.WinVerifyTrust.restype = ctypes.c_long
    wintrust.WinVerifyTrust.argtypes = (wintypes.HWND, ctypes.POINTER(_Guid), ctypes.c_void_p)

    file_info = _FileInfo(ctypes.sizeof(_FileInfo), path, None, None)
    data = _TrustData()
    data.cbStruct = ctypes.sizeof(_TrustData)
    data.dwUIChoice = _WTD_UI_NONE
    data.fdwRevocationChecks = _WTD_REVOKE_NONE
    data.dwUnionChoice = _WTD_CHOICE_FILE
    data.pFile = ctypes.pointer(file_info)
    data.dwStateAction = _WTD_STATEACTION_VERIFY
    data.dwProvFlags = _WTD_REVOCATION_CHECK_NONE
    action = _generic_verify_v2()
    no_window = wintypes.HWND(-1)  # INVALID_HANDLE_VALUE: there is nobody to ask

    status = wintrust.WinVerifyTrust(no_window, ctypes.byref(action), ctypes.byref(data))
    try:
        status &= 0xFFFFFFFF
        if status != 0:
            return Signature(status)
        name, thumbprint = _signer(wintrust, crypt32, data.hWVTStateData)
        return Signature(status, name, thumbprint)
    finally:
        data.dwStateAction = _WTD_STATEACTION_CLOSE
        wintrust.WinVerifyTrust(no_window, ctypes.byref(action), ctypes.byref(data))
