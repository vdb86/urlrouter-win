"""
ipc.py - Lightweight client-side IPC: mutex + named-pipe send.

NO Qt imports here. This module is used by both the first (tray) instance
and the short-lived second instance that just forwards a URL and exits.
Keeping it Qt-free means the second instance starts in ~150 ms instead of
3 s, because Qt6Core.dll is never loaded.

Protocol (v3)
─────────────
The client writes the UTF-8 URL followed by b"\\n", then a JSON object
describing the source app (see source_app.py; {} when unknown) followed by
b"\\n", then waits for ACK (one byte) from the server. A v2 client sends the
URL line only; the server accepts that too (no source). The pipe name keeps
its v2 suffix because the change is backward compatible.

Only an acknowledged URL counts as delivered; anything else makes the
caller fall back to opening the link itself, so a click is never lost
silently.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import time
from typing import Optional

# ------------------------------------------------------------------ kernel32

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Explicit signatures: handles are pointer-sized, never 32-bit ints.
_k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID,
                             wt.DWORD, wt.DWORD, wt.HANDLE]
_k32.CreateFileW.restype = wt.HANDLE
_k32.CreateNamedPipeW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.DWORD,
                                  wt.DWORD, wt.DWORD, wt.DWORD, wt.LPVOID]
_k32.CreateNamedPipeW.restype = wt.HANDLE
_k32.CreateMutexW.argtypes = [wt.LPVOID, wt.BOOL, wt.LPCWSTR]
_k32.CreateMutexW.restype = wt.HANDLE
_k32.ConnectNamedPipe.argtypes = [wt.HANDLE, wt.LPVOID]
_k32.ConnectNamedPipe.restype = wt.BOOL
_k32.DisconnectNamedPipe.argtypes = [wt.HANDLE]
_k32.DisconnectNamedPipe.restype = wt.BOOL
_k32.FlushFileBuffers.argtypes = [wt.HANDLE]
_k32.FlushFileBuffers.restype = wt.BOOL
_k32.ReadFile.argtypes = [wt.HANDLE, wt.LPVOID, wt.DWORD,
                          ctypes.POINTER(wt.DWORD), wt.LPVOID]
_k32.ReadFile.restype = wt.BOOL
_k32.WriteFile.argtypes = [wt.HANDLE, wt.LPCVOID, wt.DWORD,
                           ctypes.POINTER(wt.DWORD), wt.LPVOID]
_k32.WriteFile.restype = wt.BOOL
_k32.CloseHandle.argtypes = [wt.HANDLE]
_k32.CloseHandle.restype = wt.BOOL
_k32.WaitNamedPipeW.argtypes = [wt.LPCWSTR, wt.DWORD]
_k32.WaitNamedPipeW.restype = wt.BOOL
_k32.ProcessIdToSessionId.argtypes = [wt.DWORD, ctypes.POINTER(wt.DWORD)]
_k32.ProcessIdToSessionId.restype = wt.BOOL
_k32.GetCurrentProcessId.argtypes = []
_k32.GetCurrentProcessId.restype = wt.DWORD
_k32.PeekNamedPipe.argtypes = [wt.HANDLE, wt.LPVOID, wt.DWORD, ctypes.POINTER(wt.DWORD),
                               ctypes.POINTER(wt.DWORD), ctypes.POINTER(wt.DWORD)]
_k32.PeekNamedPipe.restype = wt.BOOL


def last_error() -> int:
    return ctypes.get_last_error()


def _session_id() -> int:
    sid = wt.DWORD(0)
    try:
        if _k32.ProcessIdToSessionId(_k32.GetCurrentProcessId(), ctypes.byref(sid)):
            return int(sid.value)
    except Exception:
        pass
    return 0


# ------------------------------------------------------------------ constants

# Per Windows session: two users signed in at once (fast user switching)
# must each get their own instance, and never receive each other's links.
PIPE_NAME            = rf'\\.\pipe\URLRouter_IPC_v2_s{_session_id()}'
MUTEX_NAME           = 'Local\\URLRouter_SingleInstance_v2'
BUFSIZE              = 65_536
PIPE_TIMEOUT_MS      = 2_000
SEND_RETRY_MS        = 5_000     # how long a forwarding instance keeps trying
MESSAGE_END          = b"\n"
ACK                  = b"\x06"

# Win32 values
GENERIC_READ             = 0x80000000
GENERIC_WRITE            = 0x40000000
OPEN_EXISTING            = 3
INVALID_HANDLE_VALUE     = wt.HANDLE(-1).value
ERROR_ALREADY_EXISTS     = 183
ERROR_FILE_NOT_FOUND     = 2
ERROR_BROKEN_PIPE        = 109
ERROR_PIPE_BUSY          = 231
ERROR_NO_DATA            = 232
ERROR_MORE_DATA          = 234
ERROR_PIPE_CONNECTED     = 535
PIPE_ACCESS_DUPLEX       = 0x00000003
PIPE_TYPE_BYTE           = 0x00000000
PIPE_READMODE_BYTE       = 0x00000000
PIPE_WAIT                = 0x00000000
PIPE_UNLIMITED_INSTANCES = 255


def valid_handle(handle) -> bool:
    return handle not in (None, 0, INVALID_HANDLE_VALUE)


# ------------------------------------------------------------------ mutex

_mutex_handle: Optional[int] = None


def acquire_mutex() -> bool:
    """Try to become the single running instance.
    Returns True if this is the first instance, False if one already exists."""
    global _mutex_handle
    handle = _k32.CreateMutexW(None, False, MUTEX_NAME)
    err    = last_error()
    _mutex_handle = handle
    return err != ERROR_ALREADY_EXISTS


def release_mutex() -> None:
    global _mutex_handle
    if _mutex_handle:
        _k32.CloseHandle(_mutex_handle)
        _mutex_handle = None


# ------------------------------------------------------------------ client

def _open_pipe(retry_ms: int):
    """Connect to the server pipe. The server has ONE listening instance at a
    time, so a link clicked while another is being handed over (or while the
    first instance is still starting) briefly finds the pipe busy or absent;
    keep retrying instead of dropping the URL."""
    deadline = time.monotonic() + retry_ms / 1000.0
    while True:
        handle = _k32.CreateFileW(
            PIPE_NAME, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None
        )
        if valid_handle(handle):
            return handle
        err = last_error()
        if time.monotonic() >= deadline:
            return None
        if err == ERROR_PIPE_BUSY:
            _k32.WaitNamedPipeW(PIPE_NAME, 250)
        else:
            time.sleep(0.05)


def send_to_existing(url: str, source: Optional[dict] = None,
                     retry_ms: int = SEND_RETRY_MS) -> bool:
    """Send a URL (and the app it came from) to the already-running instance
    and wait for its acknowledgement. Returns True only when the instance
    confirmed receipt. Fast: no Qt, pure Win32."""
    try:
        src = json.dumps(source or {}, ensure_ascii=True)
    except Exception:
        src = "{}"
    payload = (url.replace("\r", "").replace("\n", "").encode("utf-8") + MESSAGE_END
               + src.encode("ascii") + MESSAGE_END)
    handle  = _open_pipe(retry_ms)
    if handle is None:
        return False
    try:
        written = wt.DWORD(0)
        if not _k32.WriteFile(handle, payload, len(payload), ctypes.byref(written), None):
            return False
        if written.value != len(payload):
            return False
        ack  = ctypes.create_string_buffer(1)
        read = wt.DWORD(0)
        ok = _k32.ReadFile(handle, ack, 1, ctypes.byref(read), None)
        return bool(ok) and read.value == 1 and ack.raw[:1] == ACK
    except Exception:
        return False
    finally:
        _k32.CloseHandle(handle)
