"""
toast.py — Transient desktop notification that fades in/out in the
           bottom-right corner of the monitor under the cursor.
"""
from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve, QPropertyAnimation, QRect, Qt, QTimer,
)
from PyQt6.QtGui import (
    QBrush, QColor, QPainter, QPainterPath, QPen,
)
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget


class _ToastWidget(QWidget):
    def __init__(self, message: str, duration_ms: int = 3000) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowOpacity(0.0)

        self._radius = 12
        self._bg = QColor("#1e293b")
        self._bg.setAlphaF(0.95)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)

        lbl = QLabel(message)
        lbl.setStyleSheet(
            "color: #f1f5f9; font-family: 'Segoe UI'; font-size: 13px;"
            "background: transparent;"
        )
        lbl.setWordWrap(True)
        lbl.setMaximumWidth(320)
        layout.addWidget(lbl)

        self.adjustSize()
        self._position_on_monitor()

        # Fade in
        self._anim_in = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim_in.setDuration(220)
        self._anim_in.setStartValue(0.0)
        self._anim_in.setEndValue(1.0)
        self._anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Fade out
        self._anim_out = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim_out.setDuration(350)
        self._anim_out.setStartValue(1.0)
        self._anim_out.setEndValue(0.0)
        self._anim_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim_out.finished.connect(self.deleteLater)

        self.show()
        self._anim_in.start()

        QTimer.singleShot(duration_ms, self._start_fade_out)

    def _position_on_monitor(self) -> None:
        cursor = QApplication.instance()
        screen = cursor.screenAt(
            QApplication.instance().primaryScreen().geometry().center()
        ) if cursor is None else None

        from PyQt6.QtGui import QCursor
        pos = QCursor.pos()
        app = QApplication.instance()
        screen = app.screenAt(pos) or app.primaryScreen()
        sg = screen.geometry()

        margin = 18
        x = sg.right() - self.width() - margin
        y = sg.bottom() - self.height() - margin
        self.move(x, y)

    def _start_fade_out(self) -> None:
        self._anim_out.start()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(self._bg))
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(),
                            self._radius, self._radius)
        p.fillPath(path, QBrush(self._bg))

        # Subtle left accent bar
        accent = QColor("#3b82f6")
        p.setBrush(QBrush(accent))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, 4, self.height(), 2, 2)
        p.end()


def show_toast(message: str, duration_ms: int = 3000) -> None:
    """Display a non-blocking toast notification."""
    _ToastWidget(message, duration_ms)
