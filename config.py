"""
config.py — Load/save JSON configuration stored next to the executable.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from copy import deepcopy
from typing import Any, Dict, List, Optional


def _config_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_PATH = os.path.join(_config_dir(), "config.json")

_DEFAULT: Dict[str, Any] = {
    "version": 1,
    "appearance": {
        "position": "monitor_center",   # "monitor_center" | "custom"
        "custom_x": 0,                  # offset from monitor centre
        "custom_y": 0,
        "background_color": "#1c1c28",
        "background_opacity": 0.96,
        "text_color": "#e8e8f0",
        "corner_radius": 18,
        "padding": 22,
        "icon_size": 48,
        "show_icons": True,
        "show_names": True,
        "font_size": 13,
        "layout": "horizontal",         # "horizontal" | "vertical"
        "popup_width": 520,             # px fixed width; 0 = auto-size to content
        "url_min_font_size": 9,         # smallest font the URL field will shrink to
    },
    "general": {
        "launch_on_startup": False,
        "theme": "system",              # "system" | "light" | "dark"
    },
    "browsers": [],
    "rules": [],
}


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


class Config:
    def __init__(self) -> None:
        self._data: Dict[str, Any] = deepcopy(_DEFAULT)
        self.load()

    # ------------------------------------------------------------------ I/O

    def load(self) -> None:
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                    _deep_merge(self._data, json.load(fh))
        except Exception as exc:
            print(f"[Config] load error: {exc}")

    def save(self) -> None:
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, ensure_ascii=False)
        except Exception as exc:
            print(f"[Config] save error: {exc}")

    def to_dict(self) -> dict:
        return deepcopy(self._data)

    def from_dict(self, data: dict) -> None:
        self._data = deepcopy(_DEFAULT)
        _deep_merge(self._data, data)
        self.save()

    def reset_to_defaults(self) -> None:
        browsers = self._data.get("browsers", [])
        self._data = deepcopy(_DEFAULT)
        self._data["browsers"] = browsers
        self.save()

    # -------------------------------------------------------------- sections

    @property
    def appearance(self) -> dict:
        return self._data["appearance"]

    @property
    def general(self) -> dict:
        return self._data["general"]

    @property
    def browsers(self) -> list:
        return self._data["browsers"]

    @browsers.setter
    def browsers(self, value: list) -> None:
        self._data["browsers"] = value

    @property
    def rules(self) -> list:
        return self._data["rules"]

    @rules.setter
    def rules(self, value: list) -> None:
        self._data["rules"] = value

    # --------------------------------------------------------- helper reads

    def get_enabled_browsers(self) -> List[dict]:
        return [b for b in self.browsers if b.get("enabled", True)]

    def get_default_browser(self) -> Optional[dict]:
        for b in self.browsers:
            if b.get("is_default_fallback", False) and b.get("enabled", True):
                return b
        return None  # no explicit default → caller shows chooser

    def get_browser_by_id(self, browser_id: str) -> Optional[dict]:
        for b in self.browsers:
            if b.get("id") == browser_id:
                return b
        return None

    def get_enabled_rules(self) -> List[dict]:
        return [r for r in self.rules if r.get("enabled", True)]

    # ---------------------------------------------------------- rule helpers

    def add_rule(self, match_type: str, pattern: str, browser_id: str) -> dict:
        rule = {
            "id": str(uuid.uuid4()),
            "enabled": True,
            "match_type": match_type,
            "pattern": pattern,
            "browser_id": browser_id,
        }
        self._data["rules"].append(rule)
        self.save()
        return rule

    def update_rule(self, rule_id: str, **kwargs) -> None:
        for r in self._data["rules"]:
            if r.get("id") == rule_id:
                r.update(kwargs)
                break
        self.save()

    def delete_rule(self, rule_id: str) -> None:
        self._data["rules"] = [r for r in self._data["rules"] if r.get("id") != rule_id]
        self.save()
