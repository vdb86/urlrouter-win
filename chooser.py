"""
chooser.py — Floating browser-chooser popup.

Layout
──────
• URL shown as wrapped plain text + pencil icon to enter edit mode.
• horizontal: buttons in a row, all equal size, icon-top / name-below
• vertical  : buttons in a column, all full-width, icon-left / name-right
• Padding controls both the outer margin AND the spacing between buttons.
• Press-and-hold 600 ms → silently creates an exact_hostname rule + toast.
• Escape or click-outside dismisses.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from PyQt6.QtCore import QEvent, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QCursor, QIcon, QPainter, QPainterPath,
    QPen, QPixmap, QPolygonF,
)
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

if TYPE_CHECKING:
    from config import Config

HOLD_MS = 600


# ══════════════════════════════════════════════════════════════════════════════
#  Icons
# ══════════════════════════════════════════════════════════════════════════════

def _clipboard_icon(sz: int, color: str) -> QIcon:
    px = QPixmap(sz, sz); px.fill(Qt.GlobalColor.transparent)
    p  = QPainter(px); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c  = QColor(color)
    pen = QPen(c, 1.4); pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin); p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = max(1, sz//7); th = max(3, sz//4); tw = max(4, sz//3)
    bx = (sz-tw)//2; by = sz//5
    p.drawRoundedRect(m, by, sz-2*m, sz-by-m, 2, 2)
    p.setBrush(QBrush(c)); p.drawRoundedRect(bx, 0, tw, th+by//2, 2, 2)
    p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(c, 1))
    lx1, lx2 = m+3, sz-m-3; mid = by+(sz-by-m)//3
    p.drawLine(lx1, mid, lx2, mid); p.drawLine(lx1, mid+sz//5, lx2-2, mid+sz//5)
    p.end(); return QIcon(px)


def _pencil_icon(sz: int, color: str) -> QIcon:
    px = QPixmap(sz, sz); px.fill(Qt.GlobalColor.transparent)
    p  = QPainter(px); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c  = QColor(color); p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
    # Body: rotated parallelogram
    body = QPolygonF([QPointF(sz*.60, sz*.04), QPointF(sz*.96, sz*.40),
                      QPointF(sz*.40, sz*.96), QPointF(sz*.04, sz*.60)])
    p.drawPolygon(body)
    # Tip highlight
    p.setBrush(QBrush(QColor(255, 255, 255, 170)))
    tip = QPolygonF([QPointF(sz*.04, sz*.60), QPointF(sz*.40, sz*.96),
                     QPointF(sz*.22, sz*.78)])
    p.drawPolygon(tip)
    # Eraser divider
    pen = QPen(QColor(255, 255, 255, 120), max(1, sz/8))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap); p.setPen(pen)
    p.drawLine(QPointF(sz*.63, sz*.07), QPointF(sz*.93, sz*.37))
    p.end(); return QIcon(px)


def _btn_style(text_col: str) -> str:
    return ("background: rgba(255,255,255,0.10); border: none; border-radius: 7px;")


def _make_private_pixmap(base_px: QPixmap, icon_sz: int) -> QPixmap:
    """Add a small purple incognito badge to the bottom-right of the icon."""
    result = QPixmap(base_px)
    p = QPainter(result)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    badge = max(10, icon_sz // 3)
    bx = icon_sz - badge
    by = icon_sz - badge
    # Badge circle
    p.setBrush(QBrush(QColor("#6d28d9")))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(bx, by, badge, badge)
    # Hat dome + brim inside badge
    cx = bx + badge // 2
    r  = max(2, badge // 4)
    dome_y = by + badge // 5
    p.setBrush(QBrush(Qt.GlobalColor.white))
    p.drawEllipse(cx - r, dome_y, r * 2, r * 2)
    brim_y = dome_y + r * 2 - 1
    brim_w = max(4, badge * 2 // 3)
    p.drawRect(cx - brim_w // 2, brim_y, brim_w, max(1, badge // 7))
    p.end()
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  URL row  (wrapped label + pencil to edit + copy)
# ══════════════════════════════════════════════════════════════════════════════

class _URLRow(QWidget):
    """URL display using a QTextEdit that toggles between read-only (display)
    and editable (edit) mode via the pencil button."""

    def __init__(self, url: str, text_col: str, font_size: int,
                 parent=None) -> None:
        super().__init__(parent)
        self._url       = url
        self._text_col  = text_col
        self._font_sz   = font_size
        self._editing   = False
        self._wrap_w    = 0       # text-area width, set by set_wrap_width()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        # Single QTextEdit — toggled between read-only and editable
        self._te = QTextEdit(url)
        self._te.setWordWrapMode(__import__('PyQt6.QtGui', fromlist=['QTextOption']).QTextOption.WrapMode.WrapAnywhere)
        self._te.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._te.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._te.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._te.setReadOnly(True)
        self._te.document().setDocumentMargin(2)
        self._apply_style(editing=False)
        # Height is calculated in showEvent once the widget has its real width.
        row.addWidget(self._te, 1, Qt.AlignmentFlag.AlignTop)

        self._pencil = QPushButton()
        self._pencil.setFixedSize(32, 32)
        self._pencil.setIcon(_pencil_icon(15, text_col))
        self._pencil.setIconSize(QSize(15, 15))
        self._pencil.setToolTip("Edit URL")
        self._pencil.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._pencil.setStyleSheet(_btn_style(text_col))
        self._pencil.clicked.connect(self._toggle_edit)
        row.addWidget(self._pencil, 0, Qt.AlignmentFlag.AlignTop)

        self._copy_btn = QPushButton()
        self._copy_btn.setFixedSize(32, 32)
        self._copy_btn.setIcon(_clipboard_icon(15, text_col))
        self._copy_btn.setIconSize(QSize(15, 15))
        self._copy_btn.setToolTip("Copy URL")
        self._copy_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._copy_btn.setStyleSheet(_btn_style(text_col))
        self._copy_btn.clicked.connect(self._copy_url)
        row.addWidget(self._copy_btn, 0, Qt.AlignmentFlag.AlignTop)

    # ── public ─────────────────────────────────────────────────────
    def current_url(self) -> str:
        return self._te.toPlainText().strip() or self._url

    def set_wrap_width(self, text_area_px: int) -> None:
        """Given the pixel width the text box will occupy, compute the exact
        wrapped height synchronously (no deferred measurement) and fix it."""
        self._wrap_w = max(10, text_area_px)
        self._apply_height()

    def _apply_height(self) -> None:
        from PyQt6.QtGui import QFontMetrics, QFont as _QF
        fm     = QFontMetrics(_QF("Segoe UI", self._font_sz))
        line_h = fm.height()
        max_h  = line_h * 4 + 16            # cap at ~4 lines; scrolls beyond
        # Available text width inside the QTextEdit: subtract its 8px L/R
        # padding (4+4 from stylesheet) and 2px document margins each side.
        avail  = max(10, self._wrap_w - 8 - 8 - 4)
        text   = self._te.toPlainText() or self._url
        flags  = int(Qt.TextFlag.TextWrapAnywhere)
        rect   = fm.boundingRect(0, 0, avail, 100000, flags, text)
        needed = rect.height() + 14         # padding + margins fudge
        h      = min(max(needed, line_h + 12), max_h)
        self._te.setFixedHeight(h)

    # ── private ────────────────────────────────────────────────────
    def _toggle_edit(self) -> None:
        if self._editing:
            self._finish_edit()
        else:
            self._enter_edit()

    def _enter_edit(self) -> None:
        self._editing = True
        self._te.setReadOnly(False)
        self._apply_style(editing=True)
        self._te.setFocus()
        self._te.selectAll()
        self._pencil.setToolTip("Confirm")

    def _finish_edit(self) -> None:
        url = self._te.toPlainText().strip()
        if url:
            self._url = url
        else:
            self._te.setPlainText(self._url)
        self._editing = False
        self._te.setReadOnly(True)
        self._apply_style(editing=False)
        self._pencil.setToolTip("Edit URL")
        self._apply_height()

    def _apply_style(self, editing: bool) -> None:
        c   = self._text_col
        fs  = self._font_sz
        border = "rgba(255,255,255,0.35)" if editing else "transparent"
        bg     = "rgba(255,255,255,0.08)" if editing else "transparent"
        self._te.setStyleSheet(
            f"QTextEdit {{ color: {c}; font-size: {fs}px; font-family: 'Segoe UI';"
            f"background: {bg}; border: 1px solid {border};"
            "border-radius: 8px; padding: 4px 8px; }}"
        )

    def _resize_to_content(self) -> None:
        # Retained for the edit case: re-measure using the stored wrap width.
        self._apply_height()

    def _copy_url(self) -> None:
        QApplication.clipboard().setText(self.current_url())


# ══════════════════════════════════════════════════════════════════════════════
#  Browser button
# ══════════════════════════════════════════════════════════════════════════════

class _BrowserButton(QFrame):
    clicked        = pyqtSignal()
    hold_triggered = pyqtSignal()

    def __init__(self, name: str, pixmap=None, icon_sz: int = 48,
                 layout_dir: str = "horizontal",
                 show_icons: bool = True, show_names: bool = True,
                 font_size: int = 13, text_col: str = "#e8e8f0",
                 is_private: bool = False,
                 parent=None) -> None:
        super().__init__(parent)
        self._is_private = is_private
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(HOLD_MS)
        self._hold_timer.timeout.connect(self._on_hold)
        self._held = self._hovered = self._pressed = False
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(name)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        # horizontal → VBox (icon top, name bottom)
        # vertical   → HBox (icon left, name right)
        if layout_dir == "horizontal":
            box = QVBoxLayout(self)
            box.setAlignment(Qt.AlignmentFlag.AlignCenter)
            text_align = Qt.AlignmentFlag.AlignCenter
        else:
            box = QHBoxLayout(self)
            box.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            text_align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(8 if layout_dir == "horizontal" else 10)

        if show_icons and pixmap is not None:
            icon_lbl = QLabel()
            icon_lbl.setFixedSize(icon_sz, icon_sz)
            icon_lbl.setScaledContents(True)
            icon_lbl.setPixmap(pixmap)
            icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            icon_lbl.setStyleSheet("background: transparent;")
            item_align = Qt.AlignmentFlag.AlignHCenter if layout_dir == "horizontal" else Qt.AlignmentFlag.AlignLeft
            box.addWidget(icon_lbl, 0, item_align)

        if show_names:
            text_lbl = QLabel(name)
            text_lbl.setAlignment(text_align)
            text_lbl.setWordWrap(False)
            text_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            text_lbl.setStyleSheet(
                f"color: {text_col}; font-size: {font_size}px;"
                "font-family: 'Segoe UI'; background: transparent;"
            )
            item_align = Qt.AlignmentFlag.AlignHCenter if layout_dir == "horizontal" else Qt.AlignmentFlag.AlignLeft
            box.addWidget(text_lbl, 0, item_align)

        # Minimum size: driven by whichever is larger — icon or text
        from PyQt6.QtGui import QFontMetrics
        from PyQt6.QtGui import QFont as _QFont
        if show_names:
            fm     = QFontMetrics(_QFont("Segoe UI", font_size))
            text_w = fm.horizontalAdvance(name)
            text_h = fm.height()
        else:
            text_w = text_h = 0
        eff_icon = icon_sz if show_icons else 0
        inner    = 24   # contentsMargins are 12 px each side
        gap      = 8 if (show_icons and show_names) else 0
        if layout_dir == "horizontal":
            # Width: don't force full text width (would overflow a fixed-width
            # popup with many browsers). Icon width is the hard minimum; the
            # name label can elide/clip. Height must fit icon + text stacked.
            self.setMinimumWidth(eff_icon + inner)
            self.setMinimumHeight(eff_icon + text_h + gap + 20)
            if show_names:
                self._name_lbl_w = text_w   # used by auto-width calc
        else:
            # Vertical: full text width is fine (one button per row, popup
            # widens to fit). Height must fit the taller of icon / text.
            self.setMinimumWidth(eff_icon + text_w + gap + inner)
            self.setMinimumHeight(max(eff_icon, text_h) + 20)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._held = False; self._pressed = True
            self._hold_timer.start(); self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._hold_timer.stop(); self._pressed = False; self.update()
        if self._held: self._held = False; return
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def enterEvent(self, e) -> None:
        self._hovered = True;  self.update(); super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._hovered = False; self.update(); super().leaveEvent(e)

    def _on_hold(self) -> None:
        self._held = True; self._pressed = False
        self.update(); self.hold_triggered.emit()

    def paintEvent(self, _) -> None:
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._is_private:
            alpha   = 90 if self._pressed else (65 if self._hovered else 40)
            b_alpha = 180 if self._hovered else 120
            bg = QColor(109, 40, 217, alpha)
            bd = QColor(139, 92, 246, b_alpha)
        else:
            alpha   = 60 if self._pressed else (38 if self._hovered else 20)
            b_alpha = 70 if self._hovered else 40
            bg = QColor(255, 255, 255, alpha)
            bd = QColor(255, 255, 255, b_alpha)
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, self.width()-1, self.height()-1, 10, 10)
        p.setBrush(QBrush(bg))
        p.setPen(QPen(bd, 1))
        p.drawPath(path); p.end()


# ══════════════════════════════════════════════════════════════════════════════
#  Chooser window
# ══════════════════════════════════════════════════════════════════════════════

class ChooserWindow(QWidget):
    browser_selected = pyqtSignal(str, str, bool)  # browser_id, url, is_private
    rule_created     = pyqtSignal(str, str)

    def __init__(self, config: "Config", url: str, parent=None,
                 preview_mode: bool = False) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._config       = config
        self._original_url = url
        self._preview_mode = preview_mode
        self._build_ui()
        if not preview_mode:
            self._position()

    def _build_ui(self) -> None:
        ap         = self._config.appearance
        pad        = ap.get("padding",          22)
        icon_sz    = ap.get("icon_size",        48)
        show_icons = ap.get("show_icons",       True)
        show_names = ap.get("show_names",       True)
        layout_dir = ap.get("layout",           "horizontal")
        font_size  = ap.get("font_size",        13)
        text_col   = ap.get("text_color",       "#e8e8f0")
        popup_w    = ap.get("popup_width",       520)

        url_fs     = ap.get("url_min_font_size", 12)
        browsers   = self._config.get_enabled_browsers()
        has_private = any(b.get("private_mode", False) for b in browsers)
        n = len(browsers) or 1

        outer = QVBoxLayout(self)
        outer.setContentsMargins(pad, pad, pad, pad)
        outer.setSpacing(pad)

        # ── URL row ──────────────────────────────────────────
        self._url_row = _URLRow(self._original_url, text_col, url_fs)
        outer.addWidget(self._url_row)

        # ── Browser buttons ────────────────────────────────────
        if not browsers:
            lbl = QLabel("No browsers configured.\nOpen Settings to add some.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                f"color: {text_col}; font-size: {font_size}px; background: transparent;"
            )
            outer.addWidget(lbl)
            if popup_w > 0:
                self.setFixedWidth(popup_w)
            return

        btn_grid = QGridLayout()
        btn_grid.setSpacing(pad)          # same pad governs button→button gaps
        btn_grid.setContentsMargins(0, 0, 0, 0)

        if layout_dir == "horizontal":
            # Row 0 = normal buttons, Row 1 = matching private buttons
            for col, browser in enumerate(browsers):
                btn = self._make_btn(browser, icon_sz, show_icons, show_names,
                                     font_size, text_col, layout_dir)
                btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                btn_grid.addWidget(btn, 0, col)
                if browser.get("private_mode", False):
                    pbtn = self._make_btn(browser, icon_sz, show_icons, show_names,
                                         font_size, text_col, layout_dir, private=True)
                    pbtn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                    btn_grid.addWidget(pbtn, 1, col)
            for col in range(n):
                btn_grid.setColumnStretch(col, 1)
        else:
            # Col 0 = normal buttons, Col 1 = matching private buttons
            for row, browser in enumerate(browsers):
                btn = self._make_btn(browser, icon_sz, show_icons, show_names,
                                     font_size, text_col, layout_dir)
                btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                btn_grid.addWidget(btn, row, 0)
                if browser.get("private_mode", False):
                    pbtn = self._make_btn(browser, icon_sz, show_icons, show_names,
                                         font_size, text_col, layout_dir, private=True)
                    pbtn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                    btn_grid.addWidget(pbtn, row, 1)
            # Stretch only the columns that actually have content
            btn_grid.setColumnStretch(0, 1)
            if has_private:
                btn_grid.setColumnStretch(1, 1)

        outer.addLayout(btn_grid)

        # ── Fix popup WIDTH ─────────────────────────────────────
        if popup_w > 0:
            self.setFixedWidth(popup_w)
        else:
            def _btn_pref_w(b):
                # prefer full-name width in auto mode so names aren't clipped
                return max(b.minimumWidth(), getattr(b, "_name_lbl_w", 0) + 24)
            widest = max((_btn_pref_w(b) for b in self._iter_buttons(btn_grid)),
                         default=icon_sz + 60)
            cols   = n if layout_dir == "horizontal" else (2 if has_private else 1)
            auto_w = cols * widest + (cols - 1) * pad + 2 * pad
            self.setFixedWidth(max(auto_w, 240))

        # ── Fix popup HEIGHT to exactly fit its content ────────────────────
        # Now that the popup width is known, tell the URL row its exact text
        # width so it computes wrapped height SYNCHRONOUSLY — no racing timers.
        #   text area = popup_w − 2*pad (outer margins)
        #               − 2*32 (pencil + copy buttons)
        #               − 2*6  (URLRow inner layout spacing)
        text_area_w = self.width() - 2 * pad - 64 - 12
        self._url_row.set_wrap_width(text_area_w)

        # With every child now reporting its final height, the layout's
        # sizeHint is exact. Activate and fix the window height once.
        outer.activate()
        self.setFixedHeight(outer.sizeHint().height())
    @staticmethod
    def _iter_buttons(grid: QGridLayout):
        for i in range(grid.count()):
            wdg = grid.itemAt(i).widget()
            if isinstance(wdg, _BrowserButton):
                yield wdg

    def _make_btn(self, browser, icon_sz, show_icons, show_names,
                  font_size, text_col, layout_dir,
                  private: bool = False) -> _BrowserButton:
        from browser_utils import get_browser_icon
        name   = browser.get("name", "Browser")
        if private:
            name = f"{name} (Private)"
        pixmap = get_browser_icon(browser.get("exe_path", ""), icon_sz) if show_icons else None
        if private and pixmap is not None:
            pixmap = _make_private_pixmap(pixmap, icon_sz)

        btn = _BrowserButton(name=name, pixmap=pixmap, icon_sz=icon_sz,
                             layout_dir=layout_dir, show_icons=show_icons,
                             show_names=show_names, font_size=font_size,
                             text_col=text_col, is_private=private)
        bid = browser.get("id", "")
        btn.clicked.connect(lambda b=bid, p=private: self._open(b, p))
        btn.hold_triggered.connect(lambda b=bid, p=private: self._hold_open(b, p))
        return btn

    def _open(self, browser_id: str, private: bool = False) -> None:
        self.browser_selected.emit(browser_id, self._url_row.current_url(), private)
        self.close()

    def _hold_open(self, browser_id: str, private: bool = False) -> None:
        try:
            hostname = urlparse(self._original_url).hostname or ""
            hostname = hostname.lstrip("www.")
        except Exception:
            hostname = self._original_url
        self.rule_created.emit(browser_id, hostname)
        self.browser_selected.emit(browser_id, self._url_row.current_url(), private)
        self.close()

    def paintEvent(self, _) -> None:
        ap    = self._config.appearance
        color = QColor(ap.get("background_color", "#1c1c28"))
        color.setAlphaF(ap.get("background_opacity", 0.96))
        r = ap.get("corner_radius", 18)
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath(); path.addRoundedRect(0, 0, self.width(), self.height(), r, r)
        p.fillPath(path, QBrush(color))
        p.setPen(QPen(QColor(255,255,255,30),1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path); p.end()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape: self.close()
        super().keyPressEvent(event)

    def changeEvent(self, event) -> None:
        """Close when the window loses activation — reliable for clicks on
        any other window or the desktop, including other applications."""
        if not self._preview_mode and event.type() == QEvent.Type.ActivationChange:
            if not self.isActiveWindow():
                self.close()
        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        try: QApplication.instance().removeEventFilter(self)
        except Exception: pass
        super().closeEvent(event)

    def _position(self) -> None:
        ap     = self._config.appearance
        pos    = ap.get("position", "monitor_center")
        screen = QApplication.instance().screenAt(QCursor.pos()) \
                 or QApplication.instance().primaryScreen()
        sg     = screen.availableGeometry()

        # Never let the popup exceed the available screen height
        max_h = sg.height() - 40
        if self.height() > max_h:
            self.setFixedHeight(max_h)

        if pos == "custom":
            cx = sg.center().x() + ap.get("custom_x", 0)
            cy = sg.center().y() + ap.get("custom_y", 0)
        else:
            cx, cy = sg.center().x(), sg.center().y()
        x = max(sg.left(), min(sg.right()  - self.width(),  cx - self.width()  // 2))
        y = max(sg.top(),  min(sg.bottom() - self.height(), cy - self.height() // 2))
        self.move(x, y)
