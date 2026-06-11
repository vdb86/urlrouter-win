"""
settings_window.py — Full settings UI with six tabs:
    Browsers · Rules · Appearance · General · Import/Export · Diagnostics
"""
from __future__ import annotations

import json
import os
import uuid
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt, QSize, QRect
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QRadioButton, QScrollArea,
    QSizePolicy, QSlider, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
    QApplication, QHeaderView,
)

if TYPE_CHECKING:
    from app import URLRouterApp
    from config import Config

from router import MATCH_TYPE_LABELS, MATCH_TYPES, diagnose, hostname_from_url
import theme as _theme


# ══════════════════════════════════════════════════════════════════════════════
#  Live appearance preview  (right panel — renders actual ChooserWindow)
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

        # Minimal config proxy — real browsers, preview appearance
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

class RuleDialog(QDialog):
    def __init__(self, parent, config: "Config", rule: Optional[dict] = None) -> None:
        super().__init__(parent)
        self._config = config
        self._rule = rule
        self.setWindowTitle("Edit Rule" if rule else "Add Rule")
        self.setModal(True)
        self.setMinimumWidth(460)
        self._build()
        if rule:
            self._load(rule)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._enabled_cb = QCheckBox("Enabled")
        self._enabled_cb.setChecked(True)
        form.addRow("", self._enabled_cb)

        self._type_combo = QComboBox()
        for mt in MATCH_TYPES:
            self._type_combo.addItem(MATCH_TYPE_LABELS[mt], mt)
        form.addRow("Match type:", self._type_combo)

        self._pattern_edit = QLineEdit()
        self._pattern_edit.setPlaceholderText("e.g. google.com")
        form.addRow("Pattern:", self._pattern_edit)

        self._browser_combo = QComboBox()
        for b in self._config.get_enabled_browsers():
            self._browser_combo.addItem(b["name"], b["id"])
        form.addRow("Browser:", self._browser_combo)

        layout.addLayout(form)

        hint = QLabel()
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        self._type_combo.currentIndexChanged.connect(
            lambda _: hint.setText(self._hint_for_type(
                self._type_combo.currentData()
            ))
        )
        hint.setText(self._hint_for_type(MATCH_TYPES[0]))
        layout.addWidget(hint)

        layout.addWidget(_separator())

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._validate_and_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _hint_for_type(self, mt: str) -> str:
        hints = {
            "exact_hostname":    "Match the exact hostname, e.g. google.com",
            "wildcard_hostname": "Match subdomains, e.g. *.youtube.com",
            "url_prefix":        "URL must start with this, e.g. https://youtube.com/watch",
            "contains":          "URL must contain this text, e.g. reddit",
            "regex":             r"Regular expression, e.g. .*github\.com\/.*issues.*",
        }
        return hints.get(mt, "")

    def _load(self, rule: dict) -> None:
        self._enabled_cb.setChecked(rule.get("enabled", True))
        mt = rule.get("match_type", MATCH_TYPES[0])
        idx = self._type_combo.findData(mt)
        if idx >= 0:
            self._type_combo.setCurrentIndex(idx)
        self._pattern_edit.setText(rule.get("pattern", ""))
        bid = rule.get("browser_id", "")
        idx2 = self._browser_combo.findData(bid)
        if idx2 >= 0:
            self._browser_combo.setCurrentIndex(idx2)

    def _validate_and_accept(self) -> None:
        if not self._pattern_edit.text().strip():
            QMessageBox.warning(self, "Validation", "Pattern cannot be empty.")
            return
        if self._browser_combo.count() == 0:
            QMessageBox.warning(self, "Validation", "No browsers available.")
            return
        self.accept()

    def get_rule(self) -> dict:
        return {
            "id": self._rule["id"] if self._rule else str(uuid.uuid4()),
            "enabled": self._enabled_cb.isChecked(),
            "match_type": self._type_combo.currentData(),
            "pattern": self._pattern_edit.text().strip(),
            "browser_id": self._browser_combo.currentData(),
        }


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

        self.setWindowTitle("URL Router — Settings")
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
            'Choose "\u2014 Show chooser \u2014" to pick manually each time.'
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
        self._default_combo.addItem("— Show chooser popup (no default) —", "")
        current_default = ""
        for b in self._config.browsers:
            self._default_combo.addItem(b["name"], b["id"])
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
            self._browser_rows.append(row_widget)

            item = QListWidgetItem(self._browser_list)
            item.setSizeHint(row_widget.sizeHint())
            self._browser_list.setItemWidget(item, row_widget)

        self._refresh_default_combo()
    def _persist_browser_order(self) -> None:
        new_order = []
        for i in range(self._browser_list.count()):
            item = self._browser_list.item(i)
            widget = self._browser_list.itemWidget(item)
            if isinstance(widget, BrowserRowWidget):
                bid = widget.browser_id()
                browser = self._config.get_browser_by_id(bid)
                if browser:
                    browser["order"] = i
                    new_order.append(browser)
        self._config.browsers = new_order
        self._config.save()

    def _move_browser(self, direction: int) -> None:
        row = self._browser_list.currentRow()
        new_row = row + direction
        if new_row < 0 or new_row >= self._browser_list.count():
            return
        browsers = self._config.browsers
        browsers[row], browsers[new_row] = browsers[new_row], browsers[row]
        self._config.save()
        self._refresh_browser_list()
        self._browser_list.setCurrentRow(new_row)

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
        new_browsers = discover_browsers()
        existing_ids = {b["id"] for b in self._config.browsers}
        for nb in new_browsers:
            if nb["id"] not in existing_ids:
                self._config.browsers.append(nb)
        self._config.save()
        self._refresh_browser_list()

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

        vbox.addWidget(_section_label("Routing rules — evaluated top to bottom, first match wins"))

        self._rules_table = QTableWidget(0, 4)
        self._rules_table.setHorizontalHeaderLabels(
            ["Enabled", "Match type", "Pattern", "Browser"]
        )
        self._rules_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._rules_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._rules_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._rules_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._rules_table.setAlternatingRowColors(True)
        self._rules_table.verticalHeader().setDefaultSectionSize(36)
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

    def _refresh_rules_table(self) -> None:
        self._rules_table.setRowCount(0)
        for rule in self._config.rules:
            row = self._rules_table.rowCount()
            self._rules_table.insertRow(row)

            # Col 0: enabled checkbox
            chk = QTableWidgetItem()
            chk.setCheckState(
                Qt.CheckState.Checked if rule.get("enabled", True)
                else Qt.CheckState.Unchecked
            )
            chk.setData(Qt.ItemDataRole.UserRole, rule["id"])
            chk.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._rules_table.setItem(row, 0, chk)

            # Col 1: match type
            mt = rule.get("match_type", "")
            self._rules_table.setItem(
                row, 1, QTableWidgetItem(MATCH_TYPE_LABELS.get(mt, mt))
            )

            # Col 2: pattern
            self._rules_table.setItem(row, 2, QTableWidgetItem(rule.get("pattern", "")))

            # Col 3: browser name
            b = self._config.get_browser_by_id(rule.get("browser_id", ""))
            self._rules_table.setItem(
                row, 3, QTableWidgetItem(b["name"] if b else rule.get("browser_id", ""))
            )

        self._rules_table.itemChanged.connect(self._on_rule_item_changed)

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
        reply = QMessageBox.question(
            self, "Delete Rule",
            "Delete this rule?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            del self._config.rules[row]
            self._config.save()
            self._refresh_rules_table()

    def _move_rule(self, direction: int) -> None:
        row = self._rules_table.currentRow()
        new_row = row + direction
        if new_row < 0 or new_row >= len(self._config.rules):
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

        # ── Apply button — always visible below scroll ────────────────
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
        if not hasattr(self, "_preview_widget"):
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
            "URL Router registers itself automatically — you just need to confirm the choice."
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
                self._refresh_browser_list()
                self._refresh_rules_table()
                QMessageBox.information(self, "Import", "Configuration imported. Restart may be needed for some changes.")
            except Exception as exc:
                QMessageBox.critical(self, "Import Error", str(exc))

    def _reset_config(self) -> None:
        reply = QMessageBox.question(
            self, "Reset",
            "Reset all appearance settings and rules to defaults?\n"
            "Your browser list will be preserved.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._config.reset_to_defaults()
            self._refresh_rules_table()

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

        self._diag_result = QTextEdit()
        self._diag_result.setReadOnly(True)
        self._diag_result.setPlaceholderText("Results will appear here…")
        self._diag_result.setMinimumHeight(200)
        self._diag_result.setStyleSheet("font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px;")
        vbox.addWidget(self._diag_result)
        vbox.addStretch()
        return w

    def _run_diagnostics(self) -> None:
        url = self._diag_url.text().strip()
        if not url:
            return

        result = diagnose(url, self._config.rules)
        matched = result["matched_rule"]
        all_results = result["all_results"]

        lines = [f"URL: {url}", ""]
        if matched:
            mt = MATCH_TYPE_LABELS.get(matched.get("match_type", ""), "?")
            pat = matched.get("pattern", "")
            bid = matched.get("browser_id", "")
            b = self._config.get_browser_by_id(bid)
            browser_name = b["name"] if b else bid
            lines.append(f"✓ MATCH FOUND")
            lines.append(f"  Rule:    {mt} = {pat!r}")
            lines.append(f"  Browser: {browser_name}")
        else:
            default = self._config.get_default_browser()
            default_name = default["name"] if default else "none"
            lines.append("✗ No rule matched")
            lines.append(f"  → Chooser popup will appear")
            lines.append(f"  → Default fallback: {default_name}")

        if all_results:
            lines += ["", "── All rules evaluated ──"]
            for item in all_results:
                r = item["rule"]
                mt = MATCH_TYPE_LABELS.get(r.get("match_type", ""), "?")
                pat = r.get("pattern", "")
                hit = "✓" if item["matched"] else "✗"
                lines.append(f"  {hit}  {mt}: {pat!r}")

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
