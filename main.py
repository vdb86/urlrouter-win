"""
main.py — URL Router entry point.

Startup sequence
────────────────
1. Parse the command-line URL argument (if any).
2. Attempt to acquire the global Windows mutex.
   • Mutex already held → another instance is running; forward the URL
     over the named pipe and exit immediately.
   • Mutex acquired → we are the first instance; continue.
3. Set per-monitor DPI awareness.
4. Create QApplication, URLRouterApp, start the IPC server, show the tray.
5. If a URL was passed on the command line, handle it immediately.
6. Enter the Qt event loop.
"""
from __future__ import annotations

import ctypes
import os
import sys
import time

# Capture process start as early as possible. Set URLROUTER_DEBUG=1 to enable
# timing output to a log file next to the exe.
_T0 = time.perf_counter()
_DEBUG = os.environ.get("URLROUTER_DEBUG") == "1"


def _log(msg: str) -> None:
    if not _DEBUG:
        return
    elapsed = (time.perf_counter() - _T0) * 1000
    base = (os.path.dirname(sys.executable)
            if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(base, "timing.log"), "a", encoding="utf-8") as fh:
            fh.write(f"[{elapsed:8.1f} ms] {msg}\n")
    except Exception:
        pass


def _parse_url() -> str | None:
    """Return the first non-flag positional argument."""
    for arg in sys.argv[1:]:
        if arg.startswith("-"):
            continue
        return arg
    return None


def main() -> None:
    _log(f"process entered main(), argv={sys.argv[1:]}")
    url_arg = _parse_url()

    # ── Single-instance gate ────────────────────────────────────────────
    from ipc import acquire_mutex, send_to_existing
    _log("imported ipc")

    if not acquire_mutex():
        _log("mutex held by another instance — forwarding URL")
        if url_arg:
            ok = send_to_existing(url_arg)
            _log(f"send_to_existing returned {ok}")
        _log("second instance exiting")
        sys.exit(0)

    _log("acquired mutex — this is the first instance")

    # ── DPI awareness (must happen before QApplication) ─────────────────
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # Per-monitor v1
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    # ── Qt environment flags ─────────────────────────────────────────────
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt

    qt_app = QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(False)
    qt_app.setApplicationName("URL Router")
    qt_app.setApplicationVersion("1.0.0")
    qt_app.setOrganizationName("URLRouter")

    # Set AppUserModelID so Windows groups tray + windows together
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "URLRouter.Browser.1.0"
        )
    except Exception:
        pass

    # Set application-level icon
    from browser_utils import app_icon
    qt_app.setWindowIcon(app_icon())

    # ── Start the application ────────────────────────────────────────────
    from app import URLRouterApp

    router_app = URLRouterApp(qt_app)
    router_app.initialize()
    _log("app initialized, tray shown")

    if url_arg:
        router_app.handle_url(url_arg)
        _log("handled startup URL")

    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
