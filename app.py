"""
app.py — URLRouterApp: the central object that owns config, IPC, tray,
          chooser, and settings.  All URL delivery flows through here.
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSlot
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
        self._settings_window: Optional[object] = None
        self._ipc: Optional[IPCServer] = None

    # ---------------------------------------------------------------- init

    def initialize(self) -> None:
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
            # Don't auto-assign a default — user sets this explicitly in Settings
            self.config.browsers = browsers
            self.config.save()
        except Exception as exc:
            print(f"[App] browser discovery error: {exc}")

    # ---------------------------------------------------------------- routing

    @pyqtSlot(str)
    def handle_url(self, url: str) -> None:
        """Central URL handler — route silently or show the chooser."""
        if not url or not url.strip():
            return

        url = url.strip()

        # 1. Try rules first
        from router import route
        matched_rule = route(url, self.config.get_enabled_rules())

        if matched_rule:
            browser = self.config.get_browser_by_id(matched_rule.get("browser_id", ""))
            if browser and browser.get("enabled", True):
                self._launch(browser, url)
                return

        # 2. No rule matched — use the default fallback browser if one is set
        default = self.config.get_default_browser()
        if default:
            self._launch(default, url)
            return

        # 3. No default either — show the chooser popup
        self._show_chooser(url)

    # ------------------------------------------------------------ launching

    def _launch(self, browser: dict, url: str, private: bool = False) -> None:
        exe = browser.get("exe_path", "")
        if not exe:
            return
        try:
            args = [exe]
            if private:
                args.append(self._private_arg(exe))
            args.append(url)
            subprocess.Popen(args)
        except Exception as exc:
            print(f"[App] failed to launch {exe!r}: {exc}")
            self._show_chooser(url)

    @staticmethod
    def _private_arg(exe_path: str) -> str:
        name = os.path.basename(exe_path).lower()
        if "firefox" in name:
            return "--private-window"
        if "msedge" in name or "edge" in name:
            return "--inprivate"
        return "--incognito"  # Chrome, Brave, Vivaldi, Opera, Chromium

    # ------------------------------------------------------------- chooser

    def _show_chooser(self, url: str) -> None:
        from chooser import ChooserWindow

        # Close any lingering chooser
        if self._chooser is not None:
            try:
                self._chooser.close()
            except Exception:
                pass
            self._chooser = None

        win = ChooserWindow(self.config, url)
        win.browser_selected.connect(self._on_browser_chosen)
        win.rule_created.connect(self._on_rule_created)
        win.show()
        win.activateWindow()
        win.raise_()
        self._chooser = win

    @pyqtSlot(str, str, bool)
    def _on_browser_chosen(self, browser_id: str, url: str, private: bool) -> None:
        browser = self.config.get_browser_by_id(browser_id)
        if browser:
            self._launch(browser, url, private=private)

    @pyqtSlot(str, str)
    def _on_rule_created(self, browser_id: str, hostname: str) -> None:
        """Called when the user holds a browser button in the chooser."""
        self.config.add_rule("exact_hostname", hostname, browser_id)
        browser = self.config.get_browser_by_id(browser_id)
        name = browser["name"] if browser else browser_id
        from toast import show_toast
        show_toast(f"Rule created: {hostname}  →  {name}")

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
