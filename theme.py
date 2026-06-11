"""
theme.py — Light / dark Windows-style Qt stylesheets and theme detection.
"""
from __future__ import annotations

import winreg
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QApplication


# ----------------------------------------------------------------- detection


def is_system_dark() -> bool:
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return value == 0
    except Exception:
        return False


def resolve_theme(setting: str) -> str:
    """'system' -> 'dark'/'light' based on Windows preference."""
    if setting == "system":
        return "dark" if is_system_dark() else "light"
    return setting  # 'light' or 'dark' passed directly


# ----------------------------------------------------------------- colours


LIGHT = {
    "bg":            "#f3f3f3",
    "surface":       "#ffffff",
    "surface2":      "#f9f9f9",
    "border":        "#d1d1d1",
    "text":          "#1a1a1a",
    "text_secondary":"#6b6b6b",
    "accent":        "#0067c0",
    "accent_hover":  "#005bab",
    "accent_text":   "#ffffff",
    "button":        "#e9e9e9",
    "button_hover":  "#d9d9d9",
    "button_pressed":"#cacaca",
    "input_bg":      "#ffffff",
    "header_bg":     "#ffffff",
    "tab_selected":  "#ffffff",
    "tab_bar":       "#f0f0f0",
    "danger":        "#c42b1c",
    "danger_hover":  "#a52318",
    "row_alt":       "#f7f7f7",
    "selection_bg":  "#cce4f7",
}

DARK = {
    "bg":            "#202020",
    "surface":       "#2d2d2d",
    "surface2":      "#363636",
    "border":        "#3d3d3d",
    "text":          "#f3f3f3",
    "text_secondary":"#ababab",
    "accent":        "#4fc3f7",
    "accent_hover":  "#81d4fa",
    "accent_text":   "#000000",
    "button":        "#3d3d3d",
    "button_hover":  "#4d4d4d",
    "button_pressed":"#555555",
    "input_bg":      "#2d2d2d",
    "header_bg":     "#2a2a2a",
    "tab_selected":  "#2d2d2d",
    "tab_bar":       "#252525",
    "danger":        "#ff6b6b",
    "danger_hover":  "#ff4444",
    "row_alt":       "#313131",
    "selection_bg":  "#1a3a4a",
}


def get_colours(mode: str) -> dict:
    return DARK if mode == "dark" else LIGHT


# ---------------------------------------------------------------- stylesheet


def build_stylesheet(mode: str) -> str:
    c = get_colours(mode)
    return f"""
/* ──────── global ──────── */
QWidget {{
    background-color: {c['bg']};
    color: {c['text']};
    font-family: "Segoe UI", "Segoe UI Variable", Arial, sans-serif;
    font-size: 13px;
}}

/* Non-container widgets must be transparent so the parent
   surface (list row, tab page, etc.) shows through cleanly. */
QLabel, QCheckBox, QRadioButton {{
    background-color: transparent;
}}

/* Widgets used as embedded item-row widgets inside list/table
   views must NEVER show the window background colour —
   they must let the row's own background paint behind them. */
QListWidget QWidget,
QListWidget QLabel,
QListWidget QCheckBox,
QListWidget QRadioButton,
QTableWidget QWidget,
QTableWidget QLabel,
QTableWidget QCheckBox,
QTableWidget QRadioButton {{
    background-color: transparent;
}}

/* ──────── main window ──────── */
QMainWindow {{
    background-color: {c['bg']};
}}

/* ──────── tab widget ──────── */
QTabWidget::pane {{
    background-color: {c['surface']};
    border: 1px solid {c['border']};
    border-top: none;
    border-bottom-left-radius: 6px;
    border-bottom-right-radius: 6px;
}}
QTabBar {{
    background-color: {c['tab_bar']};
}}
QTabBar::tab {{
    background-color: {c['tab_bar']};
    color: {c['text_secondary']};
    padding: 8px 20px;
    border: 1px solid {c['border']};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
    min-width: 80px;
}}
QTabBar::tab:selected {{
    background-color: {c['tab_selected']};
    color: {c['text']};
    font-weight: 600;
    border-bottom: 1px solid {c['tab_selected']};
}}
QTabBar::tab:hover:!selected {{
    background-color: {c['button_hover']};
    color: {c['text']};
}}

/* ──────── buttons ──────── */
QPushButton {{
    background-color: {c['button']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 6px 16px;
    min-height: 30px;
    font-size: 13px;
}}
QPushButton:hover {{
    background-color: {c['button_hover']};
    border-color: {c['accent']};
}}
QPushButton:pressed {{
    background-color: {c['button_pressed']};
}}
QPushButton:disabled {{
    color: {c['text_secondary']};
    border-color: {c['border']};
}}
QPushButton[role="accent"] {{
    background-color: {c['accent']};
    color: {c['accent_text']};
    border: none;
    font-weight: 600;
}}
QPushButton[role="accent"]:hover {{
    background-color: {c['accent_hover']};
}}
QPushButton[role="danger"] {{
    background-color: {c['danger']};
    color: white;
    border: none;
}}
QPushButton[role="danger"]:hover {{
    background-color: {c['danger_hover']};
}}

/* ──────── inputs ──────── */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {c['input_bg']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 5px 9px;
    min-height: 28px;
    selection-background-color: {c['selection_bg']};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QComboBox:focus {{
    border-color: {c['accent']};
    outline: none;
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {c['surface']};
    border: 1px solid {c['border']};
    selection-background-color: {c['selection_bg']};
    selection-color: {c['text']};
    color: {c['text']};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    border: none;
    background: transparent;
    width: 16px;
}}

/* ──────── list / table ──────── */
QListWidget, QTableWidget {{
    background-color: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    alternate-background-color: {c['row_alt']};
    gridline-color: {c['border']};
    selection-background-color: {c['selection_bg']};
    selection-color: {c['text']};
    outline: none;
}}
QListWidget::item, QTableWidget::item {{
    padding: 6px 8px;
    border: none;
}}
QListWidget::item:selected, QTableWidget::item:selected {{
    background-color: {c['selection_bg']};
    color: {c['text']};
}}
QListWidget::item:hover, QTableWidget::item:hover {{
    background-color: {c['button_hover']};
}}
QHeaderView::section {{
    background-color: {c['surface2']};
    color: {c['text_secondary']};
    border: none;
    border-bottom: 1px solid {c['border']};
    border-right: 1px solid {c['border']};
    padding: 6px 10px;
    font-weight: 600;
    font-size: 12px;
}}

/* ──────── checkboxes ──────── */
QCheckBox {{
    spacing: 8px;
    color: {c['text']};
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {c['border']};
    border-radius: 4px;
    background-color: {c['input_bg']};
}}
QCheckBox::indicator:checked {{
    background-color: {c['accent']};
    border-color: {c['accent']};
}}
QCheckBox::indicator:hover {{
    border-color: {c['accent']};
}}

/* ──────── radio buttons ──────── */
QRadioButton {{
    spacing: 8px;
    color: {c['text']};
}}
QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {c['border']};
    border-radius: 8px;
    background-color: {c['input_bg']};
}}
QRadioButton::indicator:checked {{
    background-color: {c['accent']};
    border-color: {c['accent']};
}}

/* ──────── slider ──────── */
QSlider::groove:horizontal {{
    height: 4px;
    background-color: {c['border']};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background-color: {c['accent']};
    border: none;
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}}
QSlider::sub-page:horizontal {{
    background-color: {c['accent']};
    border-radius: 2px;
}}

/* ──────── scrollbars ──────── */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background-color: {c['border']};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {c['text_secondary']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none; border: none; height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background-color: {c['border']};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {c['text_secondary']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: none; border: none; width: 0;
}}

/* ──────── labels ──────── */
QLabel[role="section"] {{
    color: {c['text_secondary']};
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
QLabel[role="heading"] {{
    font-size: 15px;
    font-weight: 600;
    color: {c['text']};
}}

/* ──────── group box ──────── */
QGroupBox {{
    border: 1px solid {c['border']};
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 8px;
    font-weight: 600;
    color: {c['text_secondary']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    margin-left: 8px;
}}

/* ──────── dialogs ──────── */
QDialog {{
    background-color: {c['surface']};
}}

/* ──────── splitter ──────── */
QSplitter::handle {{
    background-color: {c['border']};
}}

/* ──────── tooltip ──────── */
QToolTip {{
    background-color: {c['surface2']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    padding: 4px 8px;
}}
"""


def apply(app: "QApplication", mode: str) -> None:
    app.setStyleSheet(build_stylesheet(mode))