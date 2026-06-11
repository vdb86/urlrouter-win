"""
registry.py — Windows registry operations:
  • Register URL Router as a browser (HKCU, no admin)
  • Discover installed browsers
  • Manage startup run key
"""
from __future__ import annotations

import os
import sys
import winreg
from typing import Dict, List, Optional

APP_NAME = "URLRouter"
PROG_ID = "URLRouterHTML"
STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _exe() -> str:
    return sys.executable if getattr(sys, "frozen", False) else os.path.abspath(sys.argv[0])


# ---------------------------------------------------------------- registration


def register_as_browser() -> None:
    """Write all necessary registry entries under HKCU (no admin required)."""
    exe = _exe()

    # ProgId
    _set(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}", "", "URL Router Document")
    _set(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}\Application",
         "ApplicationName", APP_NAME)
    _set(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}\Application",
         "ApplicationIcon", f'"{exe}",0')
    _set(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}\shell\open\command",
         "", f'"{exe}" "%1"')
    _set(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}\DefaultIcon",
         "", f'"{exe}",0')

    # StartMenuInternet entry
    base = rf"Software\Clients\StartMenuInternet\{APP_NAME}"
    _set(winreg.HKEY_CURRENT_USER, base, "", "URL Router")
    _set(winreg.HKEY_CURRENT_USER, rf"{base}\Capabilities",
         "ApplicationName", "URL Router")
    _set(winreg.HKEY_CURRENT_USER, rf"{base}\Capabilities",
         "ApplicationDescription",
         "Route every link to the right browser automatically")
    _set(winreg.HKEY_CURRENT_USER, rf"{base}\Capabilities\URLAssociations",
         "http", PROG_ID)
    _set(winreg.HKEY_CURRENT_USER, rf"{base}\Capabilities\URLAssociations",
         "https", PROG_ID)
    _set(winreg.HKEY_CURRENT_USER, rf"{base}\shell\open\command",
         "", f'"{exe}"')
    _set(winreg.HKEY_CURRENT_USER, rf"{base}\DefaultIcon",
         "", f'"{exe}",0')

    # http / https protocol handlers
    for proto in ("http", "https"):
        _set(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{proto}",
             "", f"URL:{proto.upper()} Protocol")
        _set(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{proto}",
             "URL Protocol", "")
        _set(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{proto}\shell\open\command",
             "", f'"{exe}" "%1"')
        _set(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{proto}\DefaultIcon",
             "", f'"{exe}",0')

    # RegisteredApplications
    _set(winreg.HKEY_CURRENT_USER, r"Software\RegisteredApplications",
         APP_NAME, rf"Software\Clients\StartMenuInternet\{APP_NAME}\Capabilities")


# ------------------------------------------------------------------- startup


def set_startup(enabled: bool) -> None:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY,
                             0, winreg.KEY_SET_VALUE)
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ,
                              f'"{_exe()}" --startup')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as exc:
        print(f"[Registry] startup key error: {exc}")


def is_startup_enabled() -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY)
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


# --------------------------------------------------------------- discovery


def discover_browsers() -> List[Dict]:
    """Return list of browser dicts found in the registry."""
    found: List[Dict] = []
    seen_exe: set = set()

    locations = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Clients\StartMenuInternet"),
        (winreg.HKEY_CURRENT_USER,  r"Software\Clients\StartMenuInternet"),
    ]

    for hive, base in locations:
        try:
            root = winreg.OpenKey(hive, base)
        except OSError:
            continue

        idx = 0
        while True:
            try:
                name = winreg.EnumKey(root, idx)
                idx += 1
            except OSError:
                break

            if name == APP_NAME:
                continue

            entry = _read_browser(hive, base, name)
            if entry and entry["exe_path"] not in seen_exe:
                seen_exe.add(entry["exe_path"])
                found.append(entry)

        winreg.CloseKey(root)

    # Sort alphabetically by name
    found.sort(key=lambda b: b["name"].lower())

    for i, b in enumerate(found):
        b["order"] = i

    return found


def _read_browser(hive, base: str, name: str) -> Optional[Dict]:
    try:
        kpath = rf"{base}\{name}"
        key = winreg.OpenKey(hive, kpath)
        try:
            display = winreg.QueryValue(key, None) or name
        except Exception:
            display = name

        try:
            cmd_key = winreg.OpenKey(hive, rf"{kpath}\shell\open\command")
            raw_cmd = winreg.QueryValue(cmd_key, None) or ""
            winreg.CloseKey(cmd_key)
        except Exception:
            return None

        exe = _parse_exe_from_cmd(raw_cmd)
        if not exe or not os.path.isfile(exe):
            return None

        winreg.CloseKey(key)
        return {
            "id": name.lower().replace(" ", "_"),
            "name": display,
            "exe_path": exe,
            "enabled": True,
            "is_default_fallback": False,
            "order": 0,
        }
    except Exception:
        return None


def _parse_exe_from_cmd(cmd: str) -> str:
    """Extract the executable path from a registry Open command string."""
    cmd = cmd.strip()
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        if end != -1:
            return cmd[1:end]
    # No quotes: take everything up to the first space or %
    for ch in (" ", "%"):
        idx = cmd.find(ch)
        if idx != -1:
            cmd = cmd[:idx]
    return cmd


# --------------------------------------------------------------- helpers


def _set(hive, key_path: str, value_name: str, value: str) -> None:
    try:
        key = winreg.CreateKey(hive, key_path)
        winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, value)
        winreg.CloseKey(key)
    except Exception as exc:
        print(f"[Registry] write error {key_path!r}: {exc}")


def open_default_apps() -> None:
    import os
    try:
        os.startfile("ms-settings:defaultapps")
    except Exception:
        import subprocess
        subprocess.Popen(["start", "ms-settings:defaultapps"], shell=True)
