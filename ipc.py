"""
ipc.py — Lightweight client-side IPC: mutex + named-pipe send.

NO Qt imports here. This module is used by both the first (tray) instance
and the short-lived second instance that just forwards a URL and exits.
Keeping it Qt-free means the second instance starts in ~150 ms instead of
3 s, because Qt6Core.dll is never loaded.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import time
from typing import Optional

# ------------------------------------------------------------------ constants

PIPE_NAME            = r'\\.\pipe\URLRouter_IPC_v1'
MUTEX_NAME           = 'Global\\URLRouter_SingleInstance_v1'
BUFSIZE              = 65_536
PIPE_TIMEOUT_MS      = 2_000

# Win32 values
GENERIC_WRITE            = 0x40000000
OPEN_EXISTING            = 3
INVALID_HANDLE_VALUE     = ctypes.wintypes.HANDLE(-1).value
ERROR_ALREADY_EXISTS     = 183
PIPE_ACCESS_INBOUND      = 0x00000001
PIPE_TYPE_BYTE           = 0x00000000
PIPE_READMODE_BYTE       = 0x00000000
PIPE_WAIT                = 0x00000000
PIPE_UNLIMITED_INSTANCES = 255
ERROR_PIPE_CONNECTED     = 535

_k32 = ctypes.windll.kernel32

# ------------------------------------------------------------------ mutex

_mutex_handle: Optional[int] = None


def acquire_mutex() -> bool:
    """Try to become the single running instance.
    Returns True if this is the first instance, False if one already exists."""
    global _mutex_handle
    handle = _k32.CreateMutexW(None, False, MUTEX_NAME)
    err    = _k32.GetLastError()
    _mutex_handle = handle
    return err != ERROR_ALREADY_EXISTS


def release_mutex() -> None:
    global _mutex_handle
    if _mutex_handle:
        _k32.CloseHandle(_mutex_handle)
        _mutex_handle = None


# ------------------------------------------------------------------ client

def send_to_existing(url: str) -> bool:
    """Send a URL string to the already-running instance.
    Returns True on success.  Fast: no Qt, pure Win32."""
    encoded = url.encode("utf-8")
    handle  = _k32.CreateFileW(
        PIPE_NAME, GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None
    )
    if handle == INVALID_HANDLE_VALUE:
        return False
    try:
        written = ctypes.wintypes.DWORD(0)
        ok = _k32.WriteFile(
            handle, encoded, len(encoded), ctypes.byref(written), None
        )
        return bool(ok)
    except Exception:
        return False
    finally:
        _k32.CloseHandle(handle)
