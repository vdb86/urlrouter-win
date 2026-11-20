"""
settings_window.py - Full settings UI with six tabs:
    Browsers · Rules · Appearance · General · Import/Export · Diagnostics
"""
from __future__ import annotations

import json
import os
import uuid
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt, QPoint, QSize, QRect, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QPushButton, QRadioButton, QScrollArea,
    QSizePolicy, QSlider, QSpinBox, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
    QApplication, QHeaderView,
)

if TYPE_CHECKING:
    from app import URLRouterApp
    from config import Config

from router import (
    ACTION_ASK, ACTION_EXCLUDE, ACTION_LABELS, ACTION_OPEN, ACTIONS,
    MATCH_TYPE_LABELS, MATCH_TYPES, auto_rule_name, decide,
    describe_conditions, describe_source, normalize_exe, normalize_pattern,
    rule_display_name, validate_condition,
)
import theme as _theme


# ══════════════════════════════════════════════════════════════════════════════
#  Live appearance preview  (right panel - renders actual ChooserWindow)
# ══════════════════════════════════════════════════════════════════════════════

class _LivePreview(QWidget):
    """Renders an actual ChooserWindow off-screen and displays it scaled."""

    _SAMPLE_URL = "https://example.com/some/very/long/path?q=search&ref=test"

    def __init__(self, config: "Config", parent=None) -> None:
        super().__init__(parent)
        self._config  = config
        self._pixmap: QPixmap | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(260)

    def refresh(self, ap: dict) -> None:
        from copy import deepcopy
        from chooser import ChooserWindow

        # Minimal config proxy - real browsers, preview appearance
        real_browsers = self._config.get_enabled_browsers()
        preview_data  = deepcopy(self._config.to_dict())
        preview_data["appearance"].update(ap)

        class _Cfg:
            def __init__(self, data, browsers):
                self._ap   = data["appearance"]
                self._brs  = browsers
            @property
            def appearance(self): return self._ap
            def get_enabled_browsers(self): return self._brs
            def get_default_browser(self): return None
            def get_enabled_rules(self): return []

        cfg = _Cfg(preview_data, real_browsers)
        win = ChooserWindow(cfg, self._SAMPLE_URL, preview_mode=True)
        win.move(-32000, -32000)
        win.show()
        # Sizing is fully synchronous in _build_ui now, so a single event
        # pass is enough to flush the show before grabbing the pixels.
        flag = (__import__("PyQt6.QtCore", fromlist=["QEventLoop"])
                .QEventLoop.ProcessEventsFlag.AllEvents)
        QApplication.processEvents(flag)
        self._pixmap = win.grab()
        win.close()
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Subtle desktop background
        p.fillRect(self.rect(), QBrush(QColor("#16213e")))

        # Faint grid pattern
        pen = QPen(QColor(255, 255, 255, 8), 1)
        p.setPen(pen)
        for x in range(0, self.width(), 20):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 20):
            p.drawLine(0, y, self.width(), y)

        if self._pixmap and not self._pixmap.isNull():
            pw, ph   = self._pixmap.width(), self._pixmap.height()
            avail_w  = self.width()  - 24
            avail_h  = self.height() - 24
            scale    = min(avail_w / pw, avail_h / ph, 1.0)
            dw, dh   = int(pw * scale), int(ph * scale)
            dx       = (self.width()  - dw) // 2
            dy       = (self.height() - dh) // 2
            if scale < 1.0:
                scaled = self._pixmap.scaled(
                    dw, dh,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                p.drawPixmap(dx, dy, scaled)
            else:
                p.drawPixmap(dx, dy, self._pixmap)
        else:
            p.setPen(QPen(QColor(255, 255, 255, 60)))
            p.setFont(QFont("Segoe UI", 11))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Preview\n(click Apply to refresh)")
        p.end()


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _swatch(hex_color: str, w: int = 22, h: int = 22) -> QPixmap:
    px = QPixmap(w, h)
    px.fill(QColor(hex_color))
    return px


def _spacer() -> QWidget:
    w = QWidget()
    w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return w


def _separator() -> QWidget:
    line = QWidget()
    line.setFixedHeight(1)
    line.setStyleSheet("background-color: rgba(128,128,128,0.25);")
    return line


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setProperty("role", "section")
    lbl.setStyleSheet(
        "color: #888; font-size: 11px; font-weight: 700; letter-spacing: 0.8px;"
        "padding-bottom: 2px;"
    )
    return lbl


# ══════════════════════════════════════════════════════════════════════════════
#  Rule dialog
# ══════════════════════════════════════════════════════════════════════════════

_PATTERN_HINTS = {
    "exact_hostname":    "e.g. google.com",
    "wildcard_hostname": "e.g. *.youtube.com",
    "url_prefix":        "e.g. https://youtube.com/watch",
    "contains":          "e.g. reddit",
    "regex":             r"e.g. github\.com/.*/issues",
}


class _ConditionRow(QWidget):
    """One 'match type + pattern' line in the rule editor."""
    remove_requested = pyqtSignal(object)
    changed          = pyqtSignal()

    def __init__(self, match_type: str = MATCH_TYPES[0], pattern: str = "",
                 parent=None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.type_combo = QComboBox()
        for mt in MATCH_TYPES:
            self.type_combo.addItem(MATCH_TYPE_LABELS[mt], mt)
        idx = self.type_combo.findData(match_type)
        self.type_combo.setCurrentIndex(max(0, idx))
        self.type_combo.setFixedWidth(160)
        row.addWidget(self.type_combo)

        self.pattern_edit = QLineEdit(pattern)
        row.addWidget(self.pattern_edit, 1)

        self.remove_btn = QPushButton("✕")
        # The global button padding (16px each side) would hide the glyph.
        self.remove_btn.setStyleSheet("padding: 0px; font-size: 14px;")
        self.remove_btn.setFixedWidth(36)
        self.remove_btn.setToolTip("Remove this condition")
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        row.addWidget(self.remove_btn)

        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        self.pattern_edit.textChanged.connect(lambda _: self.changed.emit())
        self._on_type_changed()

    def _on_type_changed(self, *_) -> None:
        self.pattern_edit.setPlaceholderText(
            _PATTERN_HINTS.get(self.type_combo.currentData(), ""))
        self.changed.emit()

    def value(self) -> dict:
        mt = self.type_combo.currentData()
        return {"match_type": mt,
                "pattern": normalize_pattern(mt, self.pattern_edit.text())}


class RuleDialog(QDialog):
    """Editor for one rule: name, action, conditions (OR-ed) and browsers."""

    def __init__(self, parent, config: "Config", rule: Optional[dict] = None) -> None:
        super().__init__(parent)
        self._config = config
        self._rule = rule
        self._cond_rows: list[_ConditionRow] = []
        self.setWindowTitle("Edit Rule" if rule else "Add Rule")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setMinimumHeight(320)
        # Section titles sit ABOVE the group frame here, not on its top line,
        # where they overlapped the frame and the first row of controls.
        self.setStyleSheet(
            "QGroupBox { margin-top: 24px; padding-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left;"
            " top: 0px; left: 2px; margin-left: 0px; padding: 0 4px; }"
        )
        self._build()
        self._load(rule or {})
        self._fit_height(grow_only=False)

    # ---------------------------------------------------------------- build

    def _build(self) -> None:
        # Everything above OK / Cancel scrolls, so a rule with many conditions
        # never pushes the buttons (or anything else) off screen.
        outer = QVBoxLayout(self)
        outer.setSpacing(0)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._scroll.viewport().setAutoFillBackground(False)
        self._content = QWidget()
        self._content.setObjectName("ruleContent")
        self._content.setStyleSheet("#ruleContent { background: transparent; }")
        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll, 1)

        layout = QVBoxLayout(self._content)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 12)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._enabled_cb = QCheckBox("Enabled")
        self._enabled_cb.setChecked(True)
        form.addRow("", self._enabled_cb)

        self._name_edit = QLineEdit()
        self._name_edit.setToolTip("Leave empty to use the automatic name shown in grey.")
        form.addRow("Name:", self._name_edit)

        self._action_combo = QComboBox()
        for a in ACTIONS:
            self._action_combo.addItem(ACTION_LABELS[a], a)
        form.addRow("Action:", self._action_combo)
        layout.addLayout(form)

        # ── When ─────────────────────────────────────────────────────
        when_group = QGroupBox("When the link matches any of")
        wl = QVBoxLayout(when_group)
        wl.setSpacing(8)
        self._cond_box = QVBoxLayout()
        self._cond_box.setSpacing(6)
        wl.addLayout(self._cond_box)
        add_row = QHBoxLayout()
        add_cond_btn = QPushButton("＋  Add condition")
        add_cond_btn.clicked.connect(lambda: self._add_condition())
        add_row.addWidget(add_cond_btn)
        add_row.addStretch()
        wl.addLayout(add_row)
        self._no_cond_hint = QLabel(
            "No conditions: the rule applies to every link from the apps chosen below.")
        self._no_cond_hint.setWordWrap(True)
        self._no_cond_hint.setStyleSheet("color: #888; font-size: 12px;")
        wl.addWidget(self._no_cond_hint)
        layout.addWidget(when_group)

        # ── Only when opened from ─────────────────────────────────
        src_group = QGroupBox("Only when opened from")
        sl = QVBoxLayout(src_group)
        sl.setSpacing(8)
        self._src_mode = QComboBox()
        self._src_mode.addItem("Any app", "any")
        self._src_mode.addItem("Only these apps", "only")
        self._src_mode.addItem("Any app except these", "except")
        self._src_mode.setFixedWidth(220)
        sl.addWidget(self._src_mode)
        self._src_list = QListWidget()
        self._src_list.setMaximumHeight(100)
        self._src_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        sl.addWidget(self._src_list)
        src_btns = QHBoxLayout()
        self._src_add_btn = QPushButton("＋  Add app")
        self._src_add_btn.clicked.connect(self._show_add_app_menu)
        src_btns.addWidget(self._src_add_btn)
        self._src_remove_btn = QPushButton("Remove")
        self._src_remove_btn.clicked.connect(self._remove_source_apps)
        src_btns.addWidget(self._src_remove_btn)
        src_btns.addStretch()
        sl.addLayout(src_btns)
        src_hint = QLabel("When the app is not known, rules limited to apps are skipped.")
        src_group.setToolTip(
            "The app is the program that asked Windows to open the link, or the "
            "window in front when that program is a Windows helper.")
        src_hint.setStyleSheet("color: #888; font-size: 12px;")
        sl.addWidget(src_hint)
        layout.addWidget(src_group)
        self._src_mode.currentIndexChanged.connect(self._on_source_mode_changed)

        # ── Then ─────────────────────────────────────────────────────
        then_group = QGroupBox("Then")
        tl = QVBoxLayout(then_group)
        self._then_stack = QStackedWidget()
        tl.addWidget(self._then_stack)

        # open
        open_page = QWidget()
        ol = QFormLayout(open_page)
        ol.setContentsMargins(0, 0, 0, 0)
        self._browser_combo = QComboBox()
        for b in self._config.browsers:
            label = b.get("name", b.get("id", "?"))
            if not b.get("enabled", True):
                label += "  (disabled)"
            self._browser_combo.addItem(label, b.get("id"))
        ol.addRow("Open in:", self._browser_combo)
        self._private_cb = QCheckBox("Open in a private / incognito window")
        ol.addRow("", self._private_cb)
        self._then_stack.addWidget(open_page)

        # exclude
        self._exclude_list = self._browser_check_list()
        self._then_stack.addWidget(self._labelled(
            "Never offer these browsers for matching links. A rule that opens "
            "one of them is skipped, and they are left out of the chooser.",
            self._exclude_list))

        # ask
        self._ask_list = self._browser_check_list()
        self._then_stack.addWidget(self._labelled(
            "Always show the chooser for matching links, even when a default "
            "browser is set. Offer only the browsers ticked below "
            "(none ticked = all enabled browsers).",
            self._ask_list))

        layout.addWidget(then_group)

        self._action_combo.currentIndexChanged.connect(self._on_action_changed)
        self._browser_combo.currentIndexChanged.connect(self._update_auto_name)
        self._private_cb.toggled.connect(self._update_auto_name)
        self._exclude_list.itemChanged.connect(self._update_auto_name)
        self._ask_list.itemChanged.connect(self._update_auto_name)

        layout.addStretch()

        self._footer = QWidget()
        self._footer.setObjectName("ruleFooter")
        self._footer.setStyleSheet("#ruleFooter { background: transparent; }")
        fl = QVBoxLayout(self._footer)
        fl.setSpacing(14)
        fl.setContentsMargins(20, 0, 20, 20)
        fl.addWidget(_separator())
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._validate_and_accept)
        btns.rejected.connect(self.reject)
        fl.addWidget(btns)
        outer.addWidget(self._footer)

    def _fit_height(self, grow_only: bool = True) -> None:
        """Make the dialog tall enough for its content, up to 90% of the
        screen; beyond that the content scrolls."""
        screen = self.screen() or QApplication.primaryScreen()
        limit = int(screen.availableGeometry().height() * 0.9) if screen else 900
        want = (self._content.sizeHint().height() + self._footer.sizeHint().height()
                + 2 * self._scroll.frameWidth())
        want = min(want, limit)
        if not grow_only or want > self.height():
            self.resize(max(self.width(), 560), want)

    def _browser_check_list(self) -> QListWidget:
        lst = QListWidget()
        lst.setMaximumHeight(140)
        for b in self._config.browsers:
            label = b.get("name", b.get("id", "?"))
            if not b.get("enabled", True):
                label += "  (disabled)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, b.get("id"))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            lst.addItem(item)
        return lst

    @staticmethod
    def _labelled(text: str, widget: QWidget) -> QWidget:
        page = QWidget()
        vl = QVBoxLayout(page)
        vl.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: #888; font-size: 12px;")
        vl.addWidget(lbl)
        vl.addWidget(widget)
        return page

    # ----------------------------------------------------------- conditions

    def _add_condition(self, match_type: str = MATCH_TYPES[0], pattern: str = "") -> None:
        row = _ConditionRow(match_type, pattern)
        row.remove_requested.connect(self._remove_condition)
        row.changed.connect(self._update_auto_name)
        self._cond_rows.append(row)
        self._cond_box.addWidget(row)
        self._sync_remove_buttons()
        self._update_auto_name()
        row.pattern_edit.setFocus()
        if self.isVisible():
            # Grow up to the screen limit, then keep the new row in view.
            QTimer.singleShot(0, lambda r=row: self._after_condition_added(r))

    def _after_condition_added(self, row: _ConditionRow) -> None:
        self._fit_height()

        def _show_row() -> None:
            try:
                self._scroll.ensureWidgetVisible(row, 0, 40)
            except RuntimeError:
                pass
        # After the resize has been laid out, or the row lands half hidden.
        QTimer.singleShot(0, _show_row)

    def _remove_condition(self, row: _ConditionRow) -> None:
        # Down to zero is allowed: with a source filter that means "every
        # link from those apps"; without one, OK refuses it.
        self._cond_rows.remove(row)
        self._cond_box.removeWidget(row)
        row.deleteLater()
        self._sync_remove_buttons()
        self._update_auto_name()

    def _sync_remove_buttons(self) -> None:
        if hasattr(self, "_no_cond_hint"):
            self._no_cond_hint.setVisible(not self._cond_rows)

    # ---------------------------------------------------------- source apps

    def _source_apps(self) -> list:
        return [self._src_list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self._src_list.count())]

    def _on_source_mode_changed(self, *_) -> None:
        on = self._src_mode.currentData() != "any"
        self._src_list.setEnabled(on)
        self._src_remove_btn.setEnabled(on)
        self._update_auto_name()

    def _add_source_app(self, exe: str, name: str = "", path: str = "") -> None:
        exe = normalize_exe(exe)
        if not exe:
            return
        if name or path:
            self._config.note_source_app(exe, name, path)
        if exe not in self._source_apps():
            item = QListWidgetItem(f"{self._config.app_name(exe)}   ({exe})")
            item.setData(Qt.ItemDataRole.UserRole, exe)
            self._src_list.addItem(item)
        if self._src_mode.currentData() == "any":
            self._src_mode.setCurrentIndex(self._src_mode.findData("only"))
        self._update_auto_name()

    def _remove_source_apps(self) -> None:
        for item in self._src_list.selectedItems():
            self._src_list.takeItem(self._src_list.row(item))
        self._update_auto_name()

    def _show_add_app_menu(self) -> None:
        menu = QMenu(self)
        present = set(self._source_apps())

        def header(text: str) -> None:
            act = menu.addAction(text)
            act.setEnabled(False)

        known = sorted(self._config.known_apps.items(),
                       key=lambda kv: -(kv[1].get("last_seen") or 0))
        if known:
            header("Links came from")
            for exe, info in known:
                act = menu.addAction(f"    {self._config.app_name(exe)}   ({exe})")
                act.setEnabled(exe not in present)
                act.triggered.connect(lambda _=False, e=exe: self._add_source_app(e))

        try:
            from source_app import display_name, list_window_apps
            windows = [w for w in list_window_apps()
                       if w["exe"] not in self._config.known_apps]
        except Exception:
            windows = []
        if windows:
            if known:
                menu.addSeparator()
            header("Open windows")
            for w in windows:
                name = display_name(w["path"], w["exe"])
                act = menu.addAction(f"    {name}   ({w['exe']})")
                act.setEnabled(w["exe"] not in present)
                act.triggered.connect(
                    lambda _=False, e=w["exe"], n=name, p=w["path"]:
                        self._add_source_app(e, n, p))

        if known or windows:
            menu.addSeparator()
        menu.addAction("Browse for a program…", self._browse_source_app)
        menu.addAction("Type a program name…", self._type_source_app)
        menu.exec(self._src_add_btn.mapToGlobal(QPoint(0, self._src_add_btn.height())))

    def _browse_source_app(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a program", "", "Programs (*.exe);;All files (*)")
        if not path:
            return
        path = os.path.normpath(path)
        exe = normalize_exe(path)
        try:
            from source_app import display_name
            name = display_name(path, exe)
        except Exception:
            name = ""
        self._add_source_app(exe, name, path)

    def _type_source_app(self) -> None:
        text, ok = QInputDialog.getText(
            self, "Add app", "Program file name (for example slack.exe):")
        if ok and text.strip():
            self._add_source_app(text)

    # ---------------------------------------------------------------- state

    def _on_action_changed(self, *_) -> None:
        self._then_stack.setCurrentIndex(max(0, self._action_combo.currentIndex()))
        self._update_auto_name()

    @staticmethod
    def _checked_ids(lst: QListWidget) -> list:
        return [lst.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(lst.count())
                if lst.item(i).checkState() == Qt.CheckState.Checked]

    @staticmethod
    def _set_checked(lst: QListWidget, ids: list) -> None:
        for i in range(lst.count()):
            it = lst.item(i)
            it.setCheckState(Qt.CheckState.Checked
                             if it.data(Qt.ItemDataRole.UserRole) in ids
                             else Qt.CheckState.Unchecked)

    def _update_auto_name(self, *_) -> None:
        if not hasattr(self, "_name_edit"):
            return
        try:
            auto = auto_rule_name(self._current_rule(), self._config.browser_name,
                                  self._config.app_name)
        except Exception:
            auto = ""
        self._name_edit.setPlaceholderText(auto)

    def _load(self, rule: dict) -> None:
        self._enabled_cb.setChecked(rule.get("enabled", True))
        self._name_edit.setText(rule.get("name", ""))
        action = rule.get("action", ACTION_OPEN)
        self._action_combo.setCurrentIndex(max(0, self._action_combo.findData(action)))
        self._then_stack.setCurrentIndex(max(0, self._action_combo.currentIndex()))

        conds = rule.get("conditions") or []
        if not conds and not rule.get("source_apps"):
            conds = [{"match_type": MATCH_TYPES[0], "pattern": ""}]
        for c in conds:
            self._add_condition(c.get("match_type", MATCH_TYPES[0]), c.get("pattern", ""))

        bid = rule.get("browser_id", "")
        idx = self._browser_combo.findData(bid)
        if idx >= 0:
            self._browser_combo.setCurrentIndex(idx)
        elif bid and action == ACTION_OPEN:
            # Keep the rule's target even if that browser was removed, so
            # pressing OK never retargets the rule silently.
            self._browser_combo.addItem(f"{bid}  (missing)", bid)
            self._browser_combo.setCurrentIndex(self._browser_combo.count() - 1)
        else:
            # Pre-select the first enabled browser for a new rule.
            for i, b in enumerate(self._config.browsers):
                if b.get("enabled", True):
                    self._browser_combo.setCurrentIndex(i)
                    break
        self._private_cb.setChecked(bool(rule.get("private", False)))

        apps = rule.get("source_apps") or []
        for exe in apps:
            self._add_source_app(exe)
        mode = ("except" if rule.get("source_except") else "only") if apps else "any"
        self._src_mode.setCurrentIndex(self._src_mode.findData(mode))
        self._on_source_mode_changed()
        self._sync_remove_buttons()

        ids = rule.get("browsers", []) or []
        if action == ACTION_EXCLUDE:
            self._set_checked(self._exclude_list, ids)
        elif action == ACTION_ASK:
            self._set_checked(self._ask_list, ids)
        self._update_auto_name()

    def _current_rule(self) -> dict:
        action = self._action_combo.currentData()
        rule = {
            "id": self._rule["id"] if self._rule else str(uuid.uuid4()),
            "enabled": self._enabled_cb.isChecked(),
            "name": self._name_edit.text().strip(),
            "action": action,
            "conditions": [r.value() for r in self._cond_rows],
            "source_apps": [],
            "source_except": False,
            "browser_id": "",
            "private": False,
            "browsers": [],
        }
        mode = self._src_mode.currentData()
        if mode != "any":
            rule["source_apps"] = self._source_apps()
            rule["source_except"] = mode == "except" and bool(rule["source_apps"])
        # With a source filter, untouched empty condition rows mean "any link".
        if rule["source_apps"] and all(not c["pattern"] for c in rule["conditions"]):
            rule["conditions"] = []
        if action == ACTION_OPEN:
            rule["browser_id"] = self._browser_combo.currentData() or ""
            rule["private"] = self._private_cb.isChecked()
        elif action == ACTION_EXCLUDE:
            rule["browsers"] = self._checked_ids(self._exclude_list)
        else:
            rule["browsers"] = self._checked_ids(self._ask_list)
        return rule

    def _validate_and_accept(self) -> None:
        rule = self._current_rule()
        if self._src_mode.currentData() != "any" and not rule["source_apps"]:
            QMessageBox.warning(self, "Validation",
                                "Add at least one app, or choose “Any app”.")
            return
        if not rule["conditions"] and not rule["source_apps"]:
            QMessageBox.warning(
                self, "Validation",
                "Add a condition, or choose the apps under “Only when opened from”.")
            return
        for i, c in enumerate(rule["conditions"], 1):
            err = validate_condition(c["match_type"], c["pattern"])
            if err:
                which = f"Condition {i}: " if len(rule["conditions"]) > 1 else ""
                QMessageBox.warning(self, "Validation", which + err)
                self._cond_rows[i - 1].pattern_edit.setFocus()
                return
        if rule["action"] == ACTION_OPEN and not rule["browser_id"]:
            QMessageBox.warning(self, "Validation", "No browsers available.")
            return
        if rule["action"] == ACTION_EXCLUDE and not rule["browsers"]:
            QMessageBox.warning(self, "Validation", "Tick at least one browser to never offer.")
            return
        self.accept()

    def get_rule(self) -> dict:
        return self._current_rule()


# ══════════════════════════════════════════════════════════════════════════════
#  Browser row widget (used inside QListWidget)
# ══════════════════════════════════════════════════════════════════════════════

class BrowserRowWidget(QWidget):
    def __init__(self, browser: dict, config: "Config", parent=None) -> None:
        super().__init__(parent)
        self._browser = browser
        self._config = config
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(10)

        # Icon
        from browser_utils import get_browser_icon
        exe = self._browser.get("exe_path", "")
        if exe and os.path.isfile(exe):
            px = get_browser_icon(exe, 28)
            icon_lbl = QLabel()
            icon_lbl.setPixmap(px)
            icon_lbl.setFixedSize(32, 32)
            layout.addWidget(icon_lbl)

        # Editable name
        self.name_edit = QLineEdit(self._browser.get("name", "Unknown"))
        self.name_edit.setStyleSheet("""
            QLineEdit {
                font-weight: 600;
                font-size: 13px;
                border: none;
                background: transparent;
                padding: 1px 4px;
            }
            QLineEdit:hover {
                border-bottom: 1px solid rgba(128,128,128,0.45);
            }
            QLineEdit:focus {
                border: 1px solid #0078d4;
                border-radius: 4px;
            }
        """)
        self.name_edit.setPlaceholderText("Browser name")
        self.name_edit.editingFinished.connect(self._on_name_changed)
        layout.addWidget(self.name_edit)

        layout.addWidget(_spacer())

        # Enabled checkbox
        self.enabled_cb = QCheckBox("Enabled")
        self.enabled_cb.setChecked(self._browser.get("enabled", True))
        layout.addWidget(self.enabled_cb)

        self.private_cb = QCheckBox("Private")
        self.private_cb.setToolTip("Show a private/incognito button for this browser in the chooser")
        self.private_cb.setChecked(self._browser.get("private_mode", False))
        layout.addWidget(self.private_cb)

        self.setFixedHeight(48)

    def browser_id(self) -> str:
        return self._browser.get("id", "")

    def _on_name_changed(self) -> None:
        new_name = self.name_edit.text().strip()
        if new_name and new_name != self._browser.get("name", ""):
            self._browser["name"] = new_name
            self._config.save()


# ══════════════════════════════════════════════════════════════════════════════
#  Main settings window
# ══════════════════════════════════════════════════════════════════════════════

class SettingsWindow(QMainWindow):
    def __init__(self, config: "Config", app_ref: "URLRouterApp") -> None:
        super().__init__()
        self._config = config
        self._app = app_ref
        self._theme_mode = _theme.resolve_theme(config.general.get("theme", "system"))
        self._browser_rows: list[BrowserRowWidget] = []
        # Free the window (and its live preview) when closed; the app
        # creates a fresh one next time.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self.setWindowTitle("URL Router - Settings")
        self.setMinimumSize(780, 580)
        self.resize(860, 640)

        from browser_utils import app_icon
        self.setWindowIcon(app_icon())

        self._build_ui()
        self._apply_theme()

    # ---------------------------------------------------------------- build

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        vbox = QVBoxLayout(root)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # ── Header ──────────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(54)
        header.setObjectName("header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 16, 0)

        title = QLabel("⬡  URL Router")
        title.setStyleSheet("font-size: 15px; font-weight: 700; letter-spacing: -0.3px;")
        hl.addWidget(title)
        hl.addWidget(_spacer())

        theme_lbl = QLabel("Theme:")
        theme_lbl.setStyleSheet("color: #888; font-size: 12px;")
        hl.addWidget(theme_lbl)

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["System", "Light", "Dark"])
        self._theme_combo.setFixedWidth(100)
        mapping = {"system": 0, "light": 1, "dark": 2}
        self._theme_combo.setCurrentIndex(
            mapping.get(self._config.general.get("theme", "system"), 0)
        )
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        hl.addWidget(self._theme_combo)
        vbox.addWidget(header)
        vbox.addWidget(_separator())

        # ── Tabs ────────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        vbox.addWidget(self._tabs)

        self._tabs.addTab(self._tab_browsers(),    "  Browsers  ")
        self._tabs.addTab(self._tab_rules(),       "  Rules  ")
        self._tabs.addTab(self._tab_appearance(),  "  Appearance  ")
        self._tabs.addTab(self._tab_general(),     "  General  ")
        self._tabs.addTab(self._tab_importexport(),"  Import / Export  ")
        self._tabs.addTab(self._tab_diagnostics(), "  Diagnostics  ")
        self._tabs.currentChanged.connect(
            lambda i: self._refresh_recent_sources()
            if "Diagnostics" in self._tabs.tabText(i) else None)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TAB: Browsers
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _tab_browsers(self) -> QWidget:
        w = QWidget()
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(16, 16, 16, 16)
        vbox.setSpacing(10)

        # ── Default fallback browser ─────────────────────────────────
        vbox.addWidget(_section_label("Default fallback browser"))

        fallback_desc = QLabel(
            'When no rule matches a URL, send it here directly.\n'
            'Choose "- Show chooser -" to pick manually each time.'
        )
        fallback_desc.setWordWrap(True)
        fallback_desc.setStyleSheet("color: #888; font-size: 12px;")
        vbox.addWidget(fallback_desc)

        self._default_combo = QComboBox()
        self._default_combo.setFixedWidth(300)
        self._default_combo.currentIndexChanged.connect(self._on_default_changed)
        vbox.addWidget(self._default_combo)

        vbox.addSpacing(6)
        vbox.addWidget(_separator())
        vbox.addSpacing(6)

        # ── Browser list ─────────────────────────────────────────────
        vbox.addWidget(_section_label("Installed browsers"))

        self._browser_list = QListWidget()
        # Rows are item widgets of a fixed height: the global item padding
        # would make the highlight a different size from the row it marks.
        self._browser_list.setStyleSheet("QListWidget::item { padding: 0px; margin: 0px; }")
        self._browser_list.setAlternatingRowColors(True)
        self._browser_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._browser_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._browser_list.model().rowsMoved.connect(self._persist_browser_order)
        vbox.addWidget(self._browser_list)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        rescan_btn = QPushButton("⟳  Rescan")
        rescan_btn.clicked.connect(self._rescan_browsers)
        btn_row.addWidget(rescan_btn)

        up_btn = QPushButton("↑  Move Up")
        up_btn.clicked.connect(lambda: self._move_browser(-1))
        btn_row.addWidget(up_btn)

        down_btn = QPushButton("↓  Move Down")
        down_btn.clicked.connect(lambda: self._move_browser(1))
        btn_row.addWidget(down_btn)

        btn_row.addWidget(_spacer())

        default_btn = QPushButton("Set URL Router as Default Browser →")
        default_btn.setProperty("role", "accent")
        default_btn.clicked.connect(self._open_default_apps)
        btn_row.addWidget(default_btn)

        vbox.addLayout(btn_row)
        self._refresh_browser_list()
        return w

    def _refresh_default_combo(self) -> None:
        """Rebuild the fallback-browser combo without triggering saves."""
        self._default_combo.blockSignals(True)
        self._default_combo.clear()
        self._default_combo.addItem("- Show chooser popup (no default) -", "")
        current_default = ""
        for b in self._config.browsers:
            label = b.get("name", b["id"])
            if not b.get("enabled", True):
                label += "  (disabled - chooser will show)"
            self._default_combo.addItem(label, b["id"])
            if b.get("is_default_fallback", False):
                current_default = b["id"]
        idx = self._default_combo.findData(current_default)
        self._default_combo.setCurrentIndex(max(0, idx))
        self._default_combo.blockSignals(False)

    def _on_default_changed(self, _index: int) -> None:
        chosen_id = self._default_combo.currentData()
        for b in self._config.browsers:
            b["is_default_fallback"] = (b.get("id") == chosen_id and bool(chosen_id))
        self._config.save()

    def _refresh_browser_list(self) -> None:
        self._browser_list.clear()
        self._browser_rows.clear()
        for browser in self._config.browsers:
            row_widget = BrowserRowWidget(browser, self._config)
            row_widget.enabled_cb.toggled.connect(
                lambda checked, bid=browser["id"]: self._set_browser_enabled(bid, checked)
            )
            row_widget.private_cb.toggled.connect(
                lambda checked, bid=browser["id"]: self._set_browser_private(bid, checked)
            )
            # Row saves the new name itself; then refresh everything showing names.
            row_widget.name_edit.editingFinished.connect(self._on_browser_renamed)
            self._browser_rows.append(row_widget)

            item = QListWidgetItem(self._browser_list)
            item.setData(Qt.ItemDataRole.UserRole, browser["id"])
            item.setSizeHint(QSize(row_widget.sizeHint().width(), row_widget.height()))
            self._browser_list.setItemWidget(item, row_widget)

        self._refresh_default_combo()

    def _on_browser_renamed(self) -> None:
        self._refresh_default_combo()
        self.refresh_rules()
        self._refresh_preview()

    def _persist_browser_order(self, *_) -> None:
        # Read the order from item data, not item widgets: a drag-and-drop
        # move can leave the moved row without its widget.
        new_order = []
        seen = set()
        for i in range(self._browser_list.count()):
            bid = self._browser_list.item(i).data(Qt.ItemDataRole.UserRole)
            browser = self._config.get_browser_by_id(bid)
            if browser and bid not in seen:
                seen.add(bid)
                browser["order"] = len(new_order)
                new_order.append(browser)
        # Never lose a browser if the list and config disagree.
        new_order += [b for b in self._config.browsers if b.get("id") not in seen]
        self._config.browsers = new_order
        self._config.save()
        # Rebuild after the model signal has finished, restoring row widgets.
        QTimer.singleShot(0, self._refresh_browser_list)
        QTimer.singleShot(0, self._refresh_preview)

    def _move_browser(self, direction: int) -> None:
        row = self._browser_list.currentRow()
        new_row = row + direction
        if row < 0 or new_row < 0 or new_row >= self._browser_list.count():
            return
        browsers = self._config.browsers
        browsers[row], browsers[new_row] = browsers[new_row], browsers[row]
        for i, b in enumerate(browsers):
            b["order"] = i
        self._config.save()
        self._refresh_browser_list()
        self._browser_list.setCurrentRow(new_row)
        self._refresh_preview()

    def _set_browser_enabled(self, browser_id: str, enabled: bool) -> None:
        b = self._config.get_browser_by_id(browser_id)
        if b:
            b["enabled"] = enabled
            self._config.save()
            self._refresh_default_combo()
            self._refresh_preview()

    def _set_browser_private(self, browser_id: str, private: bool) -> None:
        b = self._config.get_browser_by_id(browser_id)
        if b:
            b["private_mode"] = private
            self._config.save()
            self._refresh_preview()

    def _rescan_browsers(self) -> None:
        from registry import discover_browsers
        try:
            new_browsers = discover_browsers()
        except Exception as exc:
            QMessageBox.warning(self, "Rescan", f"Browser discovery failed:\n{exc}")
            return
        existing = {b["id"]: b for b in self._config.browsers}
        for nb in new_browsers:
            old = existing.get(nb["id"])
            if old is None:
                self._config.browsers.append(nb)
            elif not os.path.isfile(old.get("exe_path", "")):
                # The browser moved (e.g. reinstalled): keep the user's
                # settings, pick up the new executable path.
                old["exe_path"] = nb["exe_path"]
        self._config.save()
        self._refresh_browser_list()
        self.refresh_rules()
        self._refresh_preview()

    def _open_default_apps(self) -> None:
        from registry import open_default_apps
        open_default_apps()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TAB: Rules
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _tab_rules(self) -> QWidget:
        w = QWidget()
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(16, 16, 16, 16)
        vbox.setSpacing(10)

        vbox.addWidget(_section_label("Routing rules"))

        how = QLabel(
            "When several rules match, the most specific one wins. A rule that "
            "matches both the link and the app it came from beats one that matches "
            "only one of them. Then by link condition: exact hostname, wildcard "
            "hostname, URL prefix, contains, regex (a rule with only an app comes "
            "last). Between rules of the same type, the longer pattern wins; "
            "remaining ties go to the rule higher in this list. "
            "“Never offer” rules always apply on top. "
            "Use Diagnostics to see how a link is routed."
        )
        how.setWordWrap(True)
        how.setStyleSheet("color: #888; font-size: 12px;")
        vbox.addWidget(how)

        self._rules_table = QTableWidget(0, 4)
        self._rules_table.setHorizontalHeaderLabels(
            ["Enabled", "Rule", "Action", "Browser"]
        )
        hdr = self._rules_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._rules_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._rules_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._rules_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._rules_table.setAlternatingRowColors(True)
        self._rules_table.verticalHeader().setDefaultSectionSize(36)
        # Connected ONCE here; refreshes block signals while repopulating.
        self._rules_table.itemChanged.connect(self._on_rule_item_changed)
        self._rules_table.cellDoubleClicked.connect(lambda *_: self._edit_rule())
        vbox.addWidget(self._rules_table)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        add_btn = QPushButton("＋  Add")
        add_btn.setProperty("role", "accent")
        add_btn.clicked.connect(self._add_rule)
        btn_row.addWidget(add_btn)

        edit_btn = QPushButton("✏  Edit")
        edit_btn.clicked.connect(self._edit_rule)
        btn_row.addWidget(edit_btn)

        del_btn = QPushButton("✕  Delete")
        del_btn.setProperty("role", "danger")
        del_btn.clicked.connect(self._delete_rule)
        btn_row.addWidget(del_btn)

        btn_row.addWidget(_spacer())

        up_btn = QPushButton("↑  Up")
        up_btn.clicked.connect(lambda: self._move_rule(-1))
        btn_row.addWidget(up_btn)

        down_btn = QPushButton("↓  Down")
        down_btn.clicked.connect(lambda: self._move_rule(1))
        btn_row.addWidget(down_btn)

        vbox.addLayout(btn_row)
        self._refresh_rules_table()
        return w

    def refresh_rules(self) -> None:
        """Public: rebuild the rules table (e.g. after a press-and-hold rule)."""
        if hasattr(self, "_rules_table"):
            self._refresh_rules_table()

    def _refresh_rules_table(self) -> None:
        bname = self._config.browser_name
        selected = self._rules_table.currentRow()
        self._rules_table.blockSignals(True)
        try:
            self._rules_table.setRowCount(0)
            for rule in self._config.rules:
                row = self._rules_table.rowCount()
                self._rules_table.insertRow(row)

                # Col 0: enabled checkbox
                chk = QTableWidgetItem()
                chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                             | Qt.ItemFlag.ItemIsSelectable)
                chk.setCheckState(
                    Qt.CheckState.Checked if rule.get("enabled", True)
                    else Qt.CheckState.Unchecked
                )
                chk.setData(Qt.ItemDataRole.UserRole, rule["id"])
                self._rules_table.setItem(row, 0, chk)

                # Col 1: name (custom or automatic); conditions in the tooltip
                name_item = QTableWidgetItem(
                    rule_display_name(rule, bname, self._config.app_name))
                tip = [f"When: {describe_conditions(rule)}"]
                for c in rule.get("conditions", []):
                    tip.append(f"  • {MATCH_TYPE_LABELS.get(c.get('match_type'), '?')}: "
                               f"{c.get('pattern', '')}")
                src = describe_source(rule, self._config.app_name)
                if src:
                    tip.append(f"Only links {src}")
                name_item.setToolTip("\n".join(tip))
                self._rules_table.setItem(row, 1, name_item)

                # Col 2: action
                action = rule.get("action", ACTION_OPEN)
                self._rules_table.setItem(
                    row, 2, QTableWidgetItem(ACTION_LABELS.get(action, action)))

                # Col 3: browser(s)
                if action == ACTION_OPEN:
                    text = bname(rule.get("browser_id", ""))
                    if rule.get("private"):
                        text += " (private)"
                else:
                    ids = rule.get("browsers", []) or []
                    text = ", ".join(bname(b) for b in ids) if ids else "All"
                self._rules_table.setItem(row, 3, QTableWidgetItem(text))
        finally:
            self._rules_table.blockSignals(False)
        if 0 <= selected < self._rules_table.rowCount():
            self._rules_table.setCurrentCell(selected, 1)

    def _on_rule_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        rule_id = item.data(Qt.ItemDataRole.UserRole)
        enabled = item.checkState() == Qt.CheckState.Checked
        for r in self._config.rules:
            if r.get("id") == rule_id:
                r["enabled"] = enabled
                break
        self._config.save()

    def _add_rule(self) -> None:
        dlg = RuleDialog(self, self._config)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            rule = dlg.get_rule()
            self._config.rules.append(rule)
            self._config.save()
            self._refresh_rules_table()

    def _edit_rule(self) -> None:
        row = self._rules_table.currentRow()
        if row < 0 or row >= len(self._config.rules):
            return
        rule = self._config.rules[row]
        dlg = RuleDialog(self, self._config, rule)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated = dlg.get_rule()
            self._config.rules[row] = updated
            self._config.save()
            self._refresh_rules_table()

    def _delete_rule(self) -> None:
        row = self._rules_table.currentRow()
        if row < 0 or row >= len(self._config.rules):
            return
        name = rule_display_name(self._config.rules[row], self._config.browser_name,
                                 self._config.app_name)
        reply = QMessageBox.question(
            self, "Delete Rule",
            f"Delete this rule?\n\n{name}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            del self._config.rules[row]
            self._config.save()
            self._refresh_rules_table()

    def _move_rule(self, direction: int) -> None:
        row = self._rules_table.currentRow()
        new_row = row + direction
        if row < 0 or new_row < 0 or new_row >= len(self._config.rules):
            return
        rules = self._config.rules
        rules[row], rules[new_row] = rules[new_row], rules[row]
        self._config.save()
        self._refresh_rules_table()
        self._rules_table.setCurrentCell(new_row, 0)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TAB: Appearance
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    def _make_slider_spin(min_v: int, max_v: int, val: int,
                          suffix: str = "") -> tuple:
        """Return (container_widget, slider, spinbox) with bidirectional sync."""
        from PyQt6.QtWidgets import QSlider
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        sld = QSlider(Qt.Orientation.Horizontal)
        sld.setRange(min_v, max_v)
        sld.setValue(val)
        row.addWidget(sld)
        spb = QSpinBox()
        spb.setRange(min_v, max_v)
        spb.setValue(val)
        spb.setSuffix(suffix)
        spb.setFixedWidth(74)
        row.addWidget(spb)
        sld.valueChanged.connect(spb.setValue)
        spb.valueChanged.connect(sld.setValue)
        return widget, sld, spb

    def _tab_appearance(self) -> QWidget:
        ap = self._config.appearance

        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # Splitter: controls (left) | live preview (right)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # LEFT: scrollable controls
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        w = QWidget()
        scroll.setWidget(w)
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(20, 16, 20, 20)
        vbox.setSpacing(18)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 3)

        # RIGHT: live preview panel
        self._preview_widget = _LivePreview(self._config)
        splitter.addWidget(self._preview_widget)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([460, 340])
        cl.addWidget(splitter, 1)

        # ── Position ─────────────────────────────────────────────────
        pos_group = QGroupBox("Chooser Position")
        pg = QFormLayout(pos_group)
        pg.setSpacing(10)
        self._pos_combo = QComboBox()
        self._pos_combo.addItem("Centre of cursor's monitor", "monitor_center")
        self._pos_combo.addItem("Custom offset from centre",  "custom")
        self._pos_combo.setCurrentIndex(
            0 if ap.get("position") == "monitor_center" else 1
        )
        pg.addRow("Position:", self._pos_combo)

        self._custom_x = QSpinBox()
        self._custom_x.setRange(-3840, 3840)
        self._custom_x.setValue(ap.get("custom_x", 0))
        self._custom_x.setSuffix(" px")
        pg.addRow("X offset:", self._custom_x)

        self._custom_y = QSpinBox()
        self._custom_y.setRange(-2160, 2160)
        self._custom_y.setValue(ap.get("custom_y", 0))
        self._custom_y.setSuffix(" px")
        pg.addRow("Y offset:", self._custom_y)

        def _toggle_custom(_: int) -> None:
            custom = self._pos_combo.currentData() == "custom"
            self._custom_x.setEnabled(custom)
            self._custom_y.setEnabled(custom)
        self._pos_combo.currentIndexChanged.connect(_toggle_custom)
        _toggle_custom(0)
        vbox.addWidget(pos_group)

        # ── Layout ───────────────────────────────────────────────────
        layout_group = QGroupBox("Browser Button Layout")
        lg = QFormLayout(layout_group)
        lg.setSpacing(10)
        self._layout_combo = QComboBox()
        self._layout_combo.addItem("Horizontal  (icon top, name below)", "horizontal")
        self._layout_combo.addItem("Vertical  (icon left, name right)",   "vertical")
        self._layout_combo.setCurrentIndex(
            0 if ap.get("layout", "horizontal") == "horizontal" else 1
        )
        lg.addRow("Layout:", self._layout_combo)
        vbox.addWidget(layout_group)

        # ── Colours ──────────────────────────────────────────────────
        color_group = QGroupBox("Colours")
        cg = QFormLayout(color_group)
        cg.setSpacing(10)

        self._bg_color = ap.get("background_color", "#1c1c28")
        self._bg_color_btn = QPushButton()
        self._bg_color_btn.setFixedWidth(100)
        self._bg_color_btn.setIcon(QIcon(_swatch(self._bg_color)))
        self._bg_color_btn.setText(self._bg_color)
        self._bg_color_btn.clicked.connect(self._pick_bg_color)
        cg.addRow("Background:", self._bg_color_btn)

        _op_w, _op_sld, self._opacity_slider = self._make_slider_spin(
            30, 100, int(ap.get("background_opacity", 0.96) * 100), "%"
        )
        cg.addRow("Opacity:", _op_w)

        self._text_color = ap.get("text_color", "#e8e8f0")
        self._text_color_btn = QPushButton()
        self._text_color_btn.setFixedWidth(100)
        self._text_color_btn.setIcon(QIcon(_swatch(self._text_color)))
        self._text_color_btn.setText(self._text_color)
        self._text_color_btn.clicked.connect(self._pick_text_color)
        cg.addRow("Text:", self._text_color_btn)
        vbox.addWidget(color_group)

        # ── Size & Spacing ───────────────────────────────────────────
        size_group = QGroupBox("Size & Spacing")
        sg_form = QFormLayout(size_group)
        sg_form.setSpacing(10)

        _pw_w, _, self._popup_width_spin = self._make_slider_spin(
            0, 1400, ap.get("popup_width", 520), " px"
        )
        sg_form.addRow("Popup width (0 = auto):", _pw_w)

        _r_w, _, self._radius_spin = self._make_slider_spin(
            0, 48, ap.get("corner_radius", 18), " px"
        )
        sg_form.addRow("Corner radius:", _r_w)

        _pad_w, _, self._padding_spin = self._make_slider_spin(
            4, 64, ap.get("padding", 22), " px"
        )
        sg_form.addRow("Padding:", _pad_w)

        _icon_w, _, self._icon_spin = self._make_slider_spin(
            16, 96, ap.get("icon_size", 48), " px"
        )
        sg_form.addRow("Icon size:", _icon_w)

        _font_w, _, self._font_spin = self._make_slider_spin(
            9, 28, ap.get("font_size", 13), " pt"
        )
        sg_form.addRow("Label font size:", _font_w)

        _minf_w, _, self._url_min_font_spin = self._make_slider_spin(
            6, 18, ap.get("url_min_font_size", 9), " pt"
        )
        sg_form.addRow("URL font size:", _minf_w)

        vbox.addWidget(size_group)

        # ── Content ──────────────────────────────────────────────────
        vis_group = QGroupBox("Chooser Content")
        vg = QFormLayout(vis_group)
        vg.setSpacing(10)
        self._show_icons_cb = QCheckBox()
        self._show_icons_cb.setChecked(ap.get("show_icons", True))
        vg.addRow("Show icons:", self._show_icons_cb)
        self._show_names_cb = QCheckBox()
        self._show_names_cb.setChecked(ap.get("show_names", True))
        vg.addRow("Show names:", self._show_names_cb)
        vbox.addWidget(vis_group)
        vbox.addStretch()

        # ── Wire all controls → live preview ─────────────────────────
        for ctrl in (self._layout_combo, self._pos_combo,
                     self._show_icons_cb, self._show_names_cb):
            if hasattr(ctrl, "currentIndexChanged"):
                ctrl.currentIndexChanged.connect(self._refresh_preview)
            elif hasattr(ctrl, "toggled"):
                ctrl.toggled.connect(self._refresh_preview)
        for spb in (self._opacity_slider, self._radius_spin, self._padding_spin,
                    self._icon_spin, self._font_spin, self._popup_width_spin,
                    self._url_min_font_spin):
            spb.valueChanged.connect(self._refresh_preview)
        self._refresh_preview()

        # ── Apply button - always visible below scroll ────────────────
        btn_bar = QWidget()
        btn_bar.setFixedHeight(52)
        bbl = QHBoxLayout(btn_bar)
        bbl.setContentsMargins(20, 8, 20, 8)
        save_btn = QPushButton("Apply Appearance Changes")
        save_btn.setProperty("role", "accent")
        save_btn.setMinimumHeight(34)
        save_btn.clicked.connect(self._save_appearance)
        bbl.addWidget(save_btn)
        cl.addWidget(btn_bar)

        return container

    def _refresh_preview(self, *_) -> None:
        if not hasattr(self, "_preview_widget") or getattr(self, "_suppress_preview", False):
            return
        ap = {
            "background_color":   self._bg_color,
            "background_opacity": self._opacity_slider.value() / 100.0,
            "text_color":         self._text_color,
            "corner_radius":      self._radius_spin.value(),
            "padding":            self._padding_spin.value(),
            "icon_size":          self._icon_spin.value(),
            "font_size":          self._font_spin.value(),
            "layout":             self._layout_combo.currentData(),
            "show_icons":         self._show_icons_cb.isChecked(),
            "show_names":         self._show_names_cb.isChecked(),
            "popup_width":        self._popup_width_spin.value(),
            "url_min_font_size":  self._url_min_font_spin.value(),
        }
        self._preview_widget.refresh(ap)

    def _pick_bg_color(self) -> None:
        color = QColorDialog.getColor(
            QColor(self._bg_color), self, "Background colour",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if color.isValid():
            self._bg_color = color.name()
            self._bg_color_btn.setIcon(QIcon(_swatch(self._bg_color)))
            self._bg_color_btn.setText(self._bg_color)
            self._refresh_preview()

    def _pick_text_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._text_color), self, "Text colour")
        if color.isValid():
            self._text_color = color.name()
            self._text_color_btn.setIcon(QIcon(_swatch(self._text_color)))
            self._text_color_btn.setText(self._text_color)
            self._refresh_preview()

    def _save_appearance(self) -> None:
        ap = self._config.appearance
        ap["position"]             = self._pos_combo.currentData()
        ap["custom_x"]             = self._custom_x.value()
        ap["custom_y"]             = self._custom_y.value()
        ap["layout"]               = self._layout_combo.currentData()
        ap["background_color"]     = self._bg_color
        ap["background_opacity"]   = self._opacity_slider.value() / 100.0
        ap["text_color"]           = self._text_color
        ap["popup_width"]          = self._popup_width_spin.value()
        ap["corner_radius"]        = self._radius_spin.value()
        ap["padding"]              = self._padding_spin.value()
        ap["icon_size"]            = self._icon_spin.value()
        ap["font_size"]            = self._font_spin.value()
        ap["url_min_font_size"]    = self._url_min_font_spin.value()
        ap["show_icons"]           = self._show_icons_cb.isChecked()
        ap["show_names"]           = self._show_names_cb.isChecked()
        self._config.save()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TAB: General
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _tab_general(self) -> QWidget:
        w = QWidget()
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(20, 20, 20, 20)
        vbox.setSpacing(16)

        # Startup
        startup_group = QGroupBox("Startup")
        sl = QVBoxLayout(startup_group)
        sl.setSpacing(8)

        self._startup_cb = QCheckBox("Launch URL Router when Windows starts")
        from registry import is_startup_enabled
        self._startup_cb.setChecked(is_startup_enabled())
        self._startup_cb.toggled.connect(self._toggle_startup)
        sl.addWidget(self._startup_cb)

        vbox.addWidget(startup_group)

        # Default browser
        default_group = QGroupBox("Default browser")
        dl = QVBoxLayout(default_group)
        dl.setSpacing(10)

        info = QLabel(
            "To intercept all links system-wide, set URL Router as the default "
            "browser in Windows Settings.\n"
            "URL Router registers itself automatically - you just need to confirm the choice."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #888; font-size: 12px;")
        dl.addWidget(info)

        set_btn = QPushButton("Open Windows Default Apps Settings →")
        set_btn.setProperty("role", "accent")
        set_btn.setFixedWidth(320)
        set_btn.clicked.connect(self._open_default_apps)
        dl.addWidget(set_btn)

        vbox.addWidget(default_group)
        vbox.addStretch()
        return w

    def _toggle_startup(self, checked: bool) -> None:
        from registry import set_startup
        set_startup(checked)
        self._config.general["launch_on_startup"] = checked
        self._config.save()

    def _open_default_apps(self) -> None:
        from registry import open_default_apps
        open_default_apps()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TAB: Import / Export
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _tab_importexport(self) -> QWidget:
        w = QWidget()
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(20, 20, 20, 20)
        vbox.setSpacing(14)

        vbox.addWidget(_section_label("Configuration file"))

        desc = QLabel(
            "Export your entire configuration (rules, browser order, appearance) "
            "to a JSON file, or restore it from a previously exported file."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #888; font-size: 12px;")
        vbox.addWidget(desc)

        export_btn = QPushButton("⬆  Export Configuration…")
        export_btn.setFixedWidth(240)
        export_btn.clicked.connect(self._export_config)
        vbox.addWidget(export_btn)

        import_btn = QPushButton("⬇  Import Configuration…")
        import_btn.setFixedWidth(240)
        import_btn.clicked.connect(self._import_config)
        vbox.addWidget(import_btn)

        vbox.addWidget(_separator())

        reset_btn = QPushButton("Reset Appearance & Rules to Defaults")
        reset_btn.setProperty("role", "danger")
        reset_btn.setFixedWidth(280)
        reset_btn.clicked.connect(self._reset_config)
        vbox.addWidget(reset_btn)

        vbox.addStretch()
        return w

    def _export_config(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Configuration", "urlrouter_config.json",
            "JSON files (*.json)"
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(self._config.to_dict(), fh, indent=2)
                QMessageBox.information(self, "Export", "Configuration exported successfully.")
            except Exception as exc:
                QMessageBox.critical(self, "Export Error", str(exc))

    def _import_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Configuration", "", "JSON files (*.json)"
        )
        if path:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                self._config.from_dict(data)
                # The startup registry key is the source of truth, not the file.
                from registry import is_startup_enabled
                self._config.general["launch_on_startup"] = is_startup_enabled()
                self._config.save()
                self._reload_all_controls()
                QMessageBox.information(self, "Import", "Configuration imported.")
            except Exception as exc:
                QMessageBox.critical(self, "Import Error", str(exc))

    def _reset_config(self) -> None:
        reply = QMessageBox.question(
            self, "Reset",
            "Reset all appearance settings and rules to defaults?\n"
            "Your browser list and general settings will be preserved.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._config.reset_to_defaults()
            self._reload_all_controls()

    def _reload_all_controls(self) -> None:
        """Re-read every tab from config after an import or reset."""
        self._refresh_browser_list()
        self._refresh_rules_table()
        self._load_appearance_controls()
        mapping = {"system": 0, "light": 1, "dark": 2}
        self._theme_combo.blockSignals(True)
        self._theme_combo.setCurrentIndex(
            mapping.get(self._config.general.get("theme", "system"), 0))
        self._theme_combo.blockSignals(False)
        self._theme_mode = _theme.resolve_theme(self._config.general.get("theme", "system"))
        self._apply_theme()
        self._refresh_preview()

    def _load_appearance_controls(self) -> None:
        self._suppress_preview = True
        try:
            self._load_appearance_values()
        finally:
            self._suppress_preview = False

    def _load_appearance_values(self) -> None:
        ap = self._config.appearance
        self._pos_combo.setCurrentIndex(0 if ap.get("position") == "monitor_center" else 1)
        self._custom_x.setValue(ap.get("custom_x", 0))
        self._custom_y.setValue(ap.get("custom_y", 0))
        self._layout_combo.setCurrentIndex(
            0 if ap.get("layout", "horizontal") == "horizontal" else 1)
        self._bg_color = ap.get("background_color", "#1c1c28")
        self._bg_color_btn.setIcon(QIcon(_swatch(self._bg_color)))
        self._bg_color_btn.setText(self._bg_color)
        self._text_color = ap.get("text_color", "#e8e8f0")
        self._text_color_btn.setIcon(QIcon(_swatch(self._text_color)))
        self._text_color_btn.setText(self._text_color)
        self._opacity_slider.setValue(int(round(ap.get("background_opacity", 0.96) * 100)))
        self._popup_width_spin.setValue(ap.get("popup_width", 520))
        self._radius_spin.setValue(ap.get("corner_radius", 18))
        self._padding_spin.setValue(ap.get("padding", 22))
        self._icon_spin.setValue(ap.get("icon_size", 48))
        self._font_spin.setValue(ap.get("font_size", 13))
        self._url_min_font_spin.setValue(ap.get("url_min_font_size", 9))
        self._show_icons_cb.setChecked(ap.get("show_icons", True))
        self._show_names_cb.setChecked(ap.get("show_names", True))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TAB: Diagnostics
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _tab_diagnostics(self) -> QWidget:
        w = QWidget()
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(20, 20, 20, 20)
        vbox.setSpacing(12)

        vbox.addWidget(_section_label("Test URL routing"))

        desc = QLabel("Paste a URL to see which rule would match and which browser would open it.")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #888; font-size: 12px;")
        vbox.addWidget(desc)

        row = QHBoxLayout()
        self._diag_url = QLineEdit()
        self._diag_url.setPlaceholderText("https://example.com/some/path")
        self._diag_url.returnPressed.connect(self._run_diagnostics)
        row.addWidget(self._diag_url)

        test_btn = QPushButton("Test")
        test_btn.setProperty("role", "accent")
        test_btn.setFixedWidth(80)
        test_btn.clicked.connect(self._run_diagnostics)
        row.addWidget(test_btn)
        vbox.addLayout(row)

        src_row = QHBoxLayout()
        src_lbl = QLabel("Opened from:")
        src_lbl.setStyleSheet("color: #888; font-size: 12px;")
        src_row.addWidget(src_lbl)
        self._diag_source = QComboBox()
        self._diag_source.setEditable(True)
        self._diag_source.setMinimumWidth(260)
        self._diag_source.lineEdit().setPlaceholderText("not known (or type e.g. slack.exe)")
        self._diag_source.lineEdit().returnPressed.connect(self._run_diagnostics)
        self._fill_diag_sources()
        src_row.addWidget(self._diag_source)
        src_row.addStretch()
        vbox.addLayout(src_row)

        self._diag_result = QTextEdit()
        self._diag_result.setReadOnly(True)
        self._diag_result.setPlaceholderText("Results will appear here…")
        self._diag_result.setMinimumHeight(200)
        self._diag_result.setStyleSheet("font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px;")
        vbox.addWidget(self._diag_result)

        recent_head = QHBoxLayout()
        recent_head.addWidget(_section_label("Recent links and the app they came from"))
        recent_head.addStretch()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_recent_sources)
        recent_head.addWidget(refresh_btn)
        vbox.addLayout(recent_head)

        recent_desc = QLabel("Double-click a line to test that link from that app.")
        recent_desc.setStyleSheet("color: #888; font-size: 12px;")
        vbox.addWidget(recent_desc)

        self._recent_list = QListWidget()
        self._recent_list.setMinimumHeight(120)
        self._recent_list.setStyleSheet("font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px;")
        self._recent_list.itemDoubleClicked.connect(self._test_recent_source)
        vbox.addWidget(self._recent_list)
        self._refresh_recent_sources()
        return w

    def _fill_diag_sources(self) -> None:
        current = self._diag_source.currentText() if self._diag_source.count() else ""
        self._diag_source.blockSignals(True)
        self._diag_source.clear()
        self._diag_source.addItem("", "")
        known = sorted(self._config.known_apps.items(),
                       key=lambda kv: -(kv[1].get("last_seen") or 0))
        for exe, _info in known:
            self._diag_source.addItem(f"{self._config.app_name(exe)}   ({exe})", exe)
        self._diag_source.setCurrentText(current)
        self._diag_source.blockSignals(False)

    def _diag_source_exe(self) -> str:
        text = self._diag_source.currentText().strip()
        if not text:
            return ""
        idx = self._diag_source.findText(text)
        if idx >= 0 and self._diag_source.itemData(idx):
            return self._diag_source.itemData(idx)
        if text.endswith(")") and "(" in text:
            text = text.rsplit("(", 1)[1][:-1]
        return normalize_exe(text)

    def _refresh_recent_sources(self) -> None:
        import time as _time
        self._recent_list.clear()
        entries = list(getattr(self._app, "recent_sources", []) or [])
        if not entries:
            item = QListWidgetItem("No links since URL Router started.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._recent_list.addItem(item)
        for e in entries:
            when = _time.strftime("%H:%M:%S", _time.localtime(e.get("time", 0)))
            if e.get("exe"):
                who = f"{e.get('name') or self._config.app_name(e['exe'])} ({e['exe']}, via {e.get('via') or '?'})"
            else:
                who = "app not known"
            item = QListWidgetItem(f"{when}  {who}  {e.get('url', '')}")
            item.setToolTip(e.get("path") or "")
            item.setData(Qt.ItemDataRole.UserRole, e)
            self._recent_list.addItem(item)
        self._fill_diag_sources()

    def _test_recent_source(self, item: QListWidgetItem) -> None:
        e = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(e, dict):
            return
        self._diag_url.setText(e.get("url", ""))
        exe = e.get("exe", "")
        idx = self._diag_source.findData(exe) if exe else 0
        if idx >= 0:
            self._diag_source.setCurrentIndex(idx)
        else:
            self._diag_source.setCurrentText(exe)
        self._run_diagnostics()

    def _run_diagnostics(self) -> None:
        url = self._diag_url.text().strip()
        if not url:
            return
        if "://" not in url:
            url = "https://" + url   # Windows always passes a full URL

        src = self._diag_source_exe()
        d = decide(url, self._config.rules, self._config.browsers,
                   source=src or None, app_name=self._config.app_name)
        bname = self._config.browser_name

        lines = [f"URL: {url}",
                 f"Opened from: {self._config.app_name(src)} ({src})" if src
                 else "Opened from: not known", ""]
        if d.action == "open":
            lines.append("✓ A RULE OPENS IT")
            lines.append(f"  Rule:    {rule_display_name(d.rule, bname, self._config.app_name)}")
            lines.append(f"  Browser: {d.browser.get('name', '?')}"
                         + ("  (private window)" if d.private else ""))
        elif d.action == "default":
            lines.append("→ No rule decided; the DEFAULT FALLBACK opens it")
            lines.append(f"  Browser: {d.browser.get('name', '?')}")
        else:
            if d.action == "ask":
                lines.append("? An “Always ask” rule shows the CHOOSER")
                lines.append(f"  Rule:    {rule_display_name(d.rule, bname, self._config.app_name)}")
            else:
                lines.append("? Nothing decided; the CHOOSER is shown")
            offered = ", ".join(b.get("name", "?") for b in d.offered) or "none"
            lines.append(f"  Offers:  {offered}")
        if d.excluded:
            hidden = ", ".join(bname(b) for b in d.excluded)
            lines.append(f"  Hidden by “Never offer” rules: {hidden}")

        lines += ["", "── How it was decided ──"]
        lines += [f"  {step}" for step in d.trace]

        self._diag_result.setPlainText("\n".join(lines))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Theme
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _on_theme_changed(self, text: str) -> None:
        mapping = {"System": "system", "Light": "light", "Dark": "dark"}
        choice = mapping.get(text, "system")
        self._config.general["theme"] = choice
        self._config.save()
        self._theme_mode = _theme.resolve_theme(choice)
        self._apply_theme()

    def _apply_theme(self) -> None:
        _theme.apply(QApplication.instance(), self._theme_mode)

    # ---------------------------------------------------------------- close

    def closeEvent(self, event) -> None:
        self._config.save()
        super().closeEvent(event)
