"""
source_app.py - Which app was a link clicked in? (no Qt, ctypes only)

When a link is clicked, the app that was clicked in asks Windows to open it,
and Windows starts URLRouter.exe for it. Usually the app calls ShellExecute
itself, so it becomes our PARENT process (Slack, Outlook, Teams, Discord,
VS Code, Office...). Some launches go through a Windows middleman instead
(Store apps, COM activation, Explorer): then the parent says nothing useful,
and the app whose window is in the FOREGROUND is used, since the user has just
clicked in it. When neither tells anything, the middleman itself is reported.

Result: {"exe": "slack.exe", "path": "C:\\...\\slack.exe", "via": "parent"}
        via is "parent" or "foreground". None when nothing could be found.

This runs in the short-lived forwarding instance, so it must stay fast and
must never raise.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import sys
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

# Processes that only pass a launch on. A parent in this set does not tell
# which app the link came from.
BROKERS = {
    "explorer.exe", "svchost.exe", "runtimebroker.exe", "sihost.exe",
    "openwith.exe", "dllhost.exe", "launchwinapp.exe",
    "applicationframehost.exe", "rundll32.exe",
}

# Never report these as the foreground app: they are hosts, not apps.
_NOT_FOREGROUND = BROKERS - {"explorer.exe"}

# ------------------------------------------------------------------ Win32

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_u32 = ctypes.WinDLL("user32", use_last_error=True)

TH32CS_SNAPPROCESS                = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GW_OWNER                          = 4
_INVALID_HANDLE = wt.HANDLE(-1).value


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize",              wt.DWORD),
        ("cntUsage",            wt.DWORD),
        ("th32ProcessID",       wt.DWORD),
        ("th32DefaultHeapID",   ctypes.c_size_t),
        ("th32ModuleID",        wt.DWORD),
        ("cntThreads",          wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase",      ctypes.c_long),
        ("dwFlags",             wt.DWORD),
        ("szExeFile",           ctypes.c_wchar * 260),
    ]


WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

_k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
_k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
_k32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_k32.Process32FirstW.restype = wt.BOOL
_k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_k32.Process32NextW.restype = wt.BOOL
_k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_k32.OpenProcess.restype = wt.HANDLE
_k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR,
                                            ctypes.POINTER(wt.DWORD)]
_k32.QueryFullProcessImageNameW.restype = wt.BOOL
_k32.GetProcessTimes.argtypes = [wt.HANDLE] + [ctypes.POINTER(wt.FILETIME)] * 4
_k32.GetProcessTimes.restype = wt.BOOL
_k32.CloseHandle.argtypes = [wt.HANDLE]
_k32.CloseHandle.restype = wt.BOOL

_u32.GetForegroundWindow.argtypes = []
_u32.GetForegroundWindow.restype = wt.HWND
_u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
_u32.GetWindowThreadProcessId.restype = wt.DWORD
_u32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
_u32.EnumWindows.restype = wt.BOOL
_u32.EnumChildWindows.argtypes = [wt.HWND, WNDENUMPROC, wt.LPARAM]
_u32.EnumChildWindows.restype = wt.BOOL
_u32.IsWindowVisible.argtypes = [wt.HWND]
_u32.IsWindowVisible.restype = wt.BOOL
_u32.GetWindow.argtypes = [wt.HWND, wt.UINT]
_u32.GetWindow.restype = wt.HWND
_u32.GetWindowTextLengthW.argtypes = [wt.HWND]
_u32.GetWindowTextLengthW.restype = ctypes.c_int


# ------------------------------------------------------------------ processes

def _snapshot() -> Dict[int, Tuple[int, str]]:
    """pid -> (parent pid, exe file name)."""
    out: Dict[int, Tuple[int, str]] = {}
    snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (None, 0, _INVALID_HANDLE):
        return out
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = _k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            out[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID),
                                             entry.szExeFile)
            ok = _k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _k32.CloseHandle(snap)
    return out


def _open(pid: int):
    if not pid:
        return None
    h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    return h if h else None


def _image_path(pid: int) -> str:
    h = _open(pid)
    if h is None:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wt.DWORD(len(buf))
        if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
    finally:
        _k32.CloseHandle(h)
    return ""


def _creation_time(pid: int) -> int:
    h = _open(pid)
    if h is None:
        return 0
    try:
        times = [wt.FILETIME() for _ in range(4)]
        if _k32.GetProcessTimes(h, *[ctypes.byref(t) for t in times]):
            c = times[0]
            return (c.dwHighDateTime << 32) | c.dwLowDateTime
    finally:
        _k32.CloseHandle(h)
    return 0


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path)) if path else ""


def _own_path() -> str:
    return _norm(_image_path(os.getpid()) or sys.executable)


def _exe_of(path: str, fallback: str = "") -> str:
    return (os.path.basename(path) if path else fallback).lower()


# ------------------------------------------------------------------ windows

def _window_pid(hwnd) -> int:
    pid = wt.DWORD(0)
    _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _uwp_app_pid(frame_hwnd, frame_pid: int) -> int:
    """A Store app's window belongs to ApplicationFrameHost; the app itself
    owns a child window. Return that child's process, or 0."""
    found = [0]

    @WNDENUMPROC
    def _cb(child, _lp):
        pid = _window_pid(child)
        if pid and pid != frame_pid:
            found[0] = pid
            return False
        return True

    _u32.EnumChildWindows(frame_hwnd, _cb, 0)
    return found[0]


def _app_of_window(hwnd) -> Optional[Dict[str, str]]:
    pid = _window_pid(hwnd)
    path = _image_path(pid)
    exe = _exe_of(path)
    if exe == "applicationframehost.exe":
        real = _uwp_app_pid(hwnd, pid)
        if real:
            path = _image_path(real)
            exe = _exe_of(path)
    if not path:
        return None
    return {"exe": exe, "path": path}


def _foreground_app() -> Optional[Dict[str, str]]:
    hwnd = _u32.GetForegroundWindow()
    if not hwnd:
        return None
    return _app_of_window(hwnd)


# ------------------------------------------------------------------ public

def detect_source() -> Optional[Dict[str, str]]:
    """The app the link that started this process was clicked in."""
    try:
        procs = _snapshot()
        own = _own_path()
        child = os.getpid()
        parent: Optional[Dict[str, str]] = None
        for _ in range(4):
            entry = procs.get(child)
            if not entry:
                break
            ppid = entry[0]
            if not ppid or ppid not in procs:
                break
            # A parent that exited may have had its PID reused by a newer
            # process; a "parent" younger than its child is not the parent.
            ct_parent, ct_child = _creation_time(ppid), _creation_time(child)
            if ct_parent and ct_child and ct_parent > ct_child:
                break
            path = _image_path(ppid)
            if path and _norm(path) == own:
                child = ppid           # launcher stub of our own exe: go up
                continue
            parent = {"exe": _exe_of(path, procs[ppid][1]), "path": path,
                      "via": "parent"}
            break

        if parent and parent["exe"] not in BROKERS:
            return parent

        fg = _foreground_app()
        if fg and _norm(fg["path"]) != own and fg["exe"] not in _NOT_FOREGROUND:
            fg["via"] = "foreground"
            return fg
        return parent
    except Exception:
        return None


def list_window_apps() -> List[Dict[str, str]]:
    """Apps that have a visible top-level window, one entry per exe,
    for the rule editor's app picker."""
    seen: Dict[str, Dict[str, str]] = {}
    own_pid = os.getpid()

    @WNDENUMPROC
    def _cb(hwnd, _lp):
        try:
            if (not _u32.IsWindowVisible(hwnd) or _u32.GetWindow(hwnd, GW_OWNER)
                    or _u32.GetWindowTextLengthW(hwnd) == 0
                    or _window_pid(hwnd) == own_pid):
                return True
            app = _app_of_window(hwnd)
            if app and app["exe"] not in _NOT_FOREGROUND and app["exe"] not in seen:
                seen[app["exe"]] = app
        except Exception:
            pass
        return True

    try:
        _u32.EnumWindows(_cb, 0)
    except Exception:
        pass
    return sorted(seen.values(), key=lambda a: a["exe"])


@lru_cache(maxsize=256)
def display_name(path: str, exe: str = "") -> str:
    """A friendly name: the exe's file description ("Slack", "Microsoft
    Teams"), else its file name without '.exe'. Uses pywin32, so call it
    from the tray instance only."""
    if path:
        try:
            import win32api
            langs = win32api.GetFileVersionInfo(path, "\\VarFileInfo\\Translation") or []
            for key in ("FileDescription", "ProductName"):
                for lang, cp in langs:
                    val = win32api.GetFileVersionInfo(
                        path, f"\\StringFileInfo\\{lang:04x}{cp:04x}\\{key}")
                    if val and str(val).strip():
                        return str(val).strip()
        except Exception:
            pass
    name = exe or os.path.basename(path or "")
    stem = name[:-4] if name.lower().endswith(".exe") else name
    return stem[:1].upper() + stem[1:] if stem else "?"
