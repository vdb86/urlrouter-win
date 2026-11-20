"""
app.py - URLRouterApp: the central object that owns config, IPC, tray,
          chooser, and settings.  All URL delivery flows through here.
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSlot
from PyQt6.QtWidgets import QApplication

from config import Config
from ipc_server import IPCServer
import theme as _theme


class URLRouterApp(QObject):
    def __init__(self, qt_app: QApplication) -> None:
        super().__init__()
        self._qt_app = qt_app
        self.config = Config()
        self._tray = None
        self._chooser: Optional[object] = None
        self._pending: list = []          # (url, browsers) waiting for the chooser
        self._settings_window: Optional[object] = None
        self._ipc: Optional[IPCServer] = None
        # Latest links and the app each came from, newest first (Diagnostics).
        self.recent_sources: list = []

    # ---------------------------------------------------------------- init

    def initialize(self) -> None:
        # Refresh the startup registry key to the current exe path on every
        # launch. This keeps the path correct after the app is moved or rebuilt.
        try:
            from registry import set_startup, is_startup_enabled
            if is_startup_enabled():
                set_startup(True)   # rewrites key with current sys.executable
        except Exception as exc:
            print(f"[App] startup key refresh error: {exc}")

        # Register URL Router in the Windows registry
        try:
            from registry import register_as_browser
            register_as_browser()
        except Exception as exc:
            print(f"[App] registry registration error: {exc}")

        # Discover browsers if the config is empty
        if not self.config.browsers:
            self._discover_browsers()

        # Apply theme to the Qt application
        mode = _theme.resolve_theme(self.config.general.get("theme", "system"))
        _theme.apply(self._qt_app, mode)

        # Start IPC server (listens for URLs from other instances)
        self._ipc = IPCServer()
        self._ipc.url_received.connect(self.handle_url)
        self._ipc.start()

        # Create and show the tray icon
        from tray import TrayIcon
        self._tray = TrayIcon(self.config, self)
        self._tray.show()

        # Pre-warm the browser icon cache so the FIRST chooser popup paints
        # instantly instead of extracting icons on the hot path.
        self._prewarm_icons()

    def _prewarm_icons(self) -> None:
        try:
            from browser_utils import get_browser_icon
            icon_sz = self.config.appearance.get("icon_size", 48)
            for b in self.config.get_enabled_browsers():
                exe = b.get("exe_path", "")
                if exe:
                    get_browser_icon(exe, icon_sz)
        except Exception as exc:
            print(f"[App] icon prewarm error: {exc}")

    def _discover_browsers(self) -> None:
        from registry import discover_browsers
        try:
            browsers = discover_browsers()
            # Don't auto-assign a default - user sets this explicitly in Settings
            self.config.browsers = browsers
            self.config.save()
        except Exception as exc:
            print(f"[App] browser discovery error: {exc}")

    # ---------------------------------------------------------------- routing

    def handle_url(self, url: str, source: Optional[dict] = None) -> None:
        """Central URL handler - route silently or show the chooser.
        `source` is the app the link was clicked in (source_app.py) or None."""
        if not url or not url.strip():
            return

        url = url.strip()
        self._note_source(url, source)

        # Excludes → open / always-ask rules → default fallback → chooser.
        from router import decide
        d = decide(url, self.config.rules, self.config.browsers,
                   source=source, app_name=self.config.app_name)

        if d.action in ("open", "default") and d.browser is not None:
            self._launch(d.browser, url, private=d.private)
            return

        self._show_chooser(url, d.offered)

    def _note_source(self, url: str, source: Optional[dict]) -> None:
        import time
        entry = {"time": time.time(), "url": url, "exe": "", "name": "",
                 "path": "", "via": ""}
        if source and source.get("exe"):
            try:
                from source_app import display_name
                name = display_name(source.get("path", ""), source["exe"])
            except Exception:
                name = ""
            entry.update(exe=source["exe"], name=name,
                         path=source.get("path", ""), via=source.get("via", ""))
            try:
                self.config.note_source_app(source["exe"], name, source.get("path", ""))
            except Exception as exc:
                print(f"[App] note source error: {exc}")
        self.recent_sources.insert(0, entry)
        del self.recent_sources[20:]

    # ------------------------------------------------------------ launching

    def _launch(self, browser: dict, url: str, private: bool = False) -> None:
        exe = browser.get("exe_path", "")
        try:
            if not exe:
                raise FileNotFoundError("browser has no executable path")
            args = [exe]
            if private:
                args.append(self._private_arg(exe))
            args.append(url)
            subprocess.Popen(args, close_fds=True)
        except Exception as exc:
            print(f"[App] failed to launch {exe!r}: {exc}")
            self._show_chooser(url)

    @staticmethod
    def _private_arg(exe_path: str) -> str:
        name = os.path.basename(exe_path).lower()
        if (any(k in name for k in ("firefox", "waterfox", "librewolf", "floorp"))
                or name.startswith("zen")):
            return "--private-window"
        if "msedge" in name or "edge" in name:
            return "--inprivate"
        if "opera" in name:
            return "--private"
        return "--incognito"  # Chrome, Brave, Vivaldi, Chromium

    # ------------------------------------------------------------- chooser

    def _show_chooser(self, url: str, browsers: Optional[list] = None) -> None:
        # One chooser at a time. A link that arrives while one is open waits
        # its turn instead of replacing it (which used to drop the first URL).
        if self._chooser_is_open():
            self._pending.append((url, browsers))
            return

        from chooser import ChooserWindow
        win = ChooserWindow(self.config, url, browsers=browsers)
        win.browser_selected.connect(self._on_browser_chosen)
        win.rule_created.connect(self._on_rule_created)
        win.destroyed.connect(lambda *_, w=win: self._on_chooser_destroyed(w))
        win.show()
        win.activateWindow()
        win.raise_()
        self._chooser = win

    def _chooser_is_open(self) -> bool:
        if self._chooser is None:
            return False
        try:
            return self._chooser.isVisible()
        except RuntimeError:          # C++ object already deleted
            self._chooser = None
            return False

    def _on_chooser_destroyed(self, win) -> None:
        if self._chooser is win:
            self._chooser = None
        if self._pending and not self._chooser_is_open():
            url, browsers = self._pending.pop(0)
            QTimer.singleShot(0, lambda: self._show_chooser(url, browsers))

    @pyqtSlot(str, str, bool)
    def _on_browser_chosen(self, browser_id: str, url: str, private: bool) -> None:
        browser = self.config.get_browser_by_id(browser_id)
        if browser:
            self._launch(browser, url, private=private)

    @pyqtSlot(str, str, bool)
    def _on_rule_created(self, browser_id: str, hostname: str, private: bool) -> None:
        """Called when the user holds a browser button in the chooser."""
        _, created = self.config.add_quick_rule(hostname, browser_id, private)
        name = self.config.browser_name(browser_id)
        if private:
            name += " (private)"
        verb = "created" if created else "updated"
        from toast import show_toast
        show_toast(f"Rule {verb}: {hostname}  →  {name}")
        self._refresh_settings_rules()

    def _refresh_settings_rules(self) -> None:
        win = self._settings_window
        if win is None:
            return
        try:
            win.refresh_rules()
        except RuntimeError:
            self._settings_window = None

    # ----------------------------------------------------------- settings

    def open_settings(self) -> None:
        from settings_window import SettingsWindow

        if self._settings_window is not None:
            try:
                if self._settings_window.isVisible():
                    self._settings_window.raise_()
                    self._settings_window.activateWindow()
                    return
            except RuntimeError:
                self._settings_window = None

        win = SettingsWindow(self.config, self)
        win.show()
        win.raise_()
        win.activateWindow()
        self._settings_window = win

    # --------------------------------------------------------------- exit

    def quit(self) -> None:
        if self._ipc:
            self._ipc.stop()
            self._ipc.wait(2000)
        QApplication.quit()
