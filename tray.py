"""
tray.py — System-tray icon with right-click context menu.
"""
from __future__ import annotations

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon


class TrayIcon(QSystemTrayIcon):
    def __init__(self, config, app_ref) -> None:
        from browser_utils import app_icon
        super().__init__(app_icon())
        self._config = config
        self._app = app_ref

        self.setToolTip("URL Router — routing URLs to the right browser")
        self._build_menu()
        self.activated.connect(self._on_activated)

    # ---------------------------------------------------------------- menu

    def _build_menu(self) -> None:
        menu = QMenu()

        title_action = menu.addAction("URL Router")
        title_action.setEnabled(False)
        menu.addSeparator()

        open_action = QAction("Open Settings", menu)
        open_action.triggered.connect(self._app.open_settings)
        menu.addAction(open_action)

        menu.addSeparator()

        exit_action = QAction("Exit", menu)
        exit_action.triggered.connect(self._app.quit)
        menu.addAction(exit_action)

        self.setContextMenu(menu)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._app.open_settings()
