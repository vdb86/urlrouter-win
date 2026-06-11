"""
browser_utils.py — Icon extraction from browser executables using Qt's
                   built-in QFileIconProvider (no extra Win32 API needed).
                   Also provides the app's own generated icon.
"""
from __future__ import annotations

from PyQt6.QtCore import QFileInfo, QSize, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QIcon, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap, QRadialGradient,
)
from PyQt6.QtWidgets import QFileIconProvider

_provider = QFileIconProvider()
_icon_cache: dict[tuple, QPixmap] = {}   # (exe_path, size) → QPixmap


def get_browser_icon(exe_path: str, size: int = 48) -> QPixmap:
    """Return a QPixmap at exactly *size* × *size* pixels.

    Gets the largest native icon variant Qt knows about for the exe, then
    downscales (or upscales as last resort) with SmoothTransformation so
    the result is always the exact requested pixel size.
    """
    key = (exe_path, size)
    if key in _icon_cache:
        return _icon_cache[key]

    icon = _provider.icon(QFileInfo(exe_path))
    if icon.isNull():
        icon = _fallback_icon()

    # Use the largest available variant for best downscale quality
    available = [s for s in icon.availableSizes() if s.width() > 0]
    if available:
        best = max(available, key=lambda s: s.width())
        px = icon.pixmap(best)
    else:
        # Provider didn't enumerate sizes — ask for a generous base
        px = icon.pixmap(QSize(max(size, 256), max(size, 256)))

    if px.isNull():
        px = _fallback_icon().pixmap(QSize(size, size))

    # Scale to the exact requested square size.
    # Browser icons are always square so IgnoreAspectRatio gives a clean fill.
    if px.width() != size or px.height() != size:
        px = px.scaled(
            size, size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    _icon_cache[key] = px
    return px


def _fallback_icon() -> QIcon:
    px = QPixmap(48, 48)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor("#4a90d9")))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(2, 2, 44, 44)
    p.setPen(QPen(QColor("#ffffff"), 3))
    p.setFont(p.font())
    p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "?")
    p.end()
    return QIcon(px)


# ----------------------------------------------------------------- app icon


_app_icon_cache: QIcon | None = None


def app_icon() -> QIcon:
    global _app_icon_cache
    if _app_icon_cache is None:
        _app_icon_cache = _load_or_generate_app_icon()
    return _app_icon_cache


def _load_or_generate_app_icon() -> QIcon:
    """Load icon.png from next to the exe, fall back to programmatic icon."""
    import os, sys
    base = (os.path.dirname(sys.executable)
            if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__)))
    png_path = os.path.join(base, "icon.png")
    if os.path.isfile(png_path):
        icon = QIcon(png_path)
        if not icon.isNull():
            return icon
    return _generate_app_icon()


def _generate_app_icon() -> QIcon:
    icon = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_render_icon(sz))
    return icon


def _render_icon(sz: int) -> QPixmap:
    px = QPixmap(sz, sz)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Circle background – deep blue gradient
    grad = QRadialGradient(sz * 0.45, sz * 0.38, sz * 0.52)
    grad.setColorAt(0.0, QColor("#2979ff"))
    grad.setColorAt(1.0, QColor("#0046cc"))
    path = QPainterPath()
    m = max(1, sz // 16)
    path.addEllipse(m, m, sz - 2 * m, sz - 2 * m)
    p.fillPath(path, QBrush(grad))

    # Draw three small dots on the left + one on the right + lines/arrow
    pen = QPen(QColor("#ffffff"), max(1, sz // 22))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)

    cx = sz / 2.0
    cy = sz / 2.0

    # Three input dots
    dot_r = max(1.5, sz / 18)
    p.setBrush(QBrush(QColor("#ffffff")))
    p.setPen(Qt.PenStyle.NoPen)
    for dy in (-sz * 0.28, 0.0, sz * 0.28):
        lx = cx - sz * 0.30
        ly = cy + dy
        p.drawEllipse(
            int(lx - dot_r), int(ly - dot_r),
            int(dot_r * 2), int(dot_r * 2),
        )

    # Lines from dots to centre
    pen2 = QPen(QColor("#ffffff"), max(1, sz // 24))
    pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen2)
    for dy in (-sz * 0.28, 0.0, sz * 0.28):
        lx = cx - sz * 0.30 + dot_r
        ly = cy + dy
        p.drawLine(int(lx), int(ly), int(cx), int(cy))

    # Right arrow
    p.setBrush(QBrush(QColor("#ffffff")))
    p.setPen(Qt.PenStyle.NoPen)
    ax = cx + sz * 0.04
    aw = sz * 0.30
    ah = sz * 0.22
    stem_h = ah * 0.38
    arrow = QPainterPath()
    arrow.moveTo(ax, cy - stem_h / 2)
    arrow.lineTo(ax + aw * 0.55, cy - stem_h / 2)
    arrow.lineTo(ax + aw * 0.55, cy - ah / 2)
    arrow.lineTo(ax + aw, cy)
    arrow.lineTo(ax + aw * 0.55, cy + ah / 2)
    arrow.lineTo(ax + aw * 0.55, cy + stem_h / 2)
    arrow.lineTo(ax, cy + stem_h / 2)
    arrow.closeSubpath()
    p.fillPath(arrow, QBrush(QColor("#ffffff")))

    p.end()
    return px
