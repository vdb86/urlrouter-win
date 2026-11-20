"""
config.py - Load/save JSON configuration stored next to the executable.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import uuid
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from router import ACTION_OPEN, default_app_name, normalize_exe, normalize_rule


def _config_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_PATH = os.path.join(_config_dir(), "config.json")
CONFIG_VERSION = 2

_DEFAULT: Dict[str, Any] = {
    "version": CONFIG_VERSION,
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
        "url_min_font_size": 9,         # font size of the URL field
    },
    "general": {
        "launch_on_startup": False,
        "theme": "system",              # "system" | "light" | "dark"
    },
    "browsers": [],
    "rules": [],
    # Apps links have come from: exe -> {"name", "path", "last_seen"}.
    # Feeds the rule editor's app picker and friendly names.
    "known_apps": {},
}


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _migrate(data: Dict[str, Any]) -> None:
    """Upgrade rules to the current shape in place; drop unusable entries."""
    for section in ("appearance", "general"):
        if not isinstance(data.get(section), dict):
            data[section] = deepcopy(_DEFAULT[section])
    if not isinstance(data.get("rules"), list):
        data["rules"] = []
    if not isinstance(data.get("browsers"), list):
        data["browsers"] = []
    data["browsers"] = [b for b in data["browsers"] if isinstance(b, dict) and b.get("id")]
    data["rules"] = [r for r in (normalize_rule(x) for x in data["rules"]) if r]
    apps = data.get("known_apps")
    data["known_apps"] = {
        normalize_exe(k): v for k, v in (apps.items() if isinstance(apps, dict) else [])
        if normalize_exe(k) and isinstance(v, dict)
    }
    data["version"] = CONFIG_VERSION


class Config:
    def __init__(self) -> None:
        self._data: Dict[str, Any] = deepcopy(_DEFAULT)
        self.load()

    # ------------------------------------------------------------------ I/O

    def load(self) -> None:
        if not os.path.exists(CONFIG_PATH):
            return
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if not isinstance(loaded, dict):
                raise ValueError("config root is not an object")
        except Exception as exc:
            # Keep the unreadable file so the next save cannot destroy it.
            print(f"[Config] load error: {exc}")
            try:
                stamp = time.strftime("%Y%m%d-%H%M%S")
                shutil.copy2(CONFIG_PATH, f"{CONFIG_PATH}.broken-{stamp}")
            except Exception:
                pass
            return
        old_version = loaded.get("version", 1)
        _deep_merge(self._data, loaded)
        _migrate(self._data)
        if old_version != CONFIG_VERSION:
            # Older builds cannot read the new rule shape: keep their file.
            try:
                backup = f"{CONFIG_PATH}.v{old_version}.bak"
                if not os.path.exists(backup):
                    shutil.copy2(CONFIG_PATH, backup)
            except Exception:
                pass
            self.save()

    def save(self) -> None:
        # Write to a temp file and swap it in, so a crash mid-write can never
        # leave a truncated config.json behind.
        tmp = CONFIG_PATH + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, CONFIG_PATH)
        except Exception as exc:
            print(f"[Config] save error: {exc}")

    def to_dict(self) -> dict:
        return deepcopy(self._data)

    def from_dict(self, data: dict) -> None:
        if not isinstance(data, dict):
            raise ValueError("Not a URL Router configuration file.")
        known = deepcopy(self.known_apps)
        fresh = deepcopy(_DEFAULT)
        _deep_merge(fresh, deepcopy(data))
        _migrate(fresh)
        # Apps seen on THIS computer stay known; imported ones are added.
        for exe, info in known.items():
            fresh["known_apps"].setdefault(exe, info)
        self._data = fresh
        self.save()

    def reset_to_defaults(self) -> None:
        """Reset appearance and rules; keep browsers, general settings and
        the apps links have come from."""
        browsers = self._data.get("browsers", [])
        general = self._data.get("general", deepcopy(_DEFAULT["general"]))
        known = self._data.get("known_apps", {})
        self._data = deepcopy(_DEFAULT)
        self._data["browsers"] = browsers
        self._data["general"] = general
        self._data["known_apps"] = known
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

    @property
    def known_apps(self) -> dict:
        return self._data.setdefault("known_apps", {})

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

    def browser_name(self, browser_id: str) -> str:
        b = self.get_browser_by_id(browser_id)
        return b.get("name", browser_id) if b else (browser_id or "?")

    def app_name(self, exe: str) -> str:
        """Friendly name of a source app ('slack.exe' -> 'Slack')."""
        info = self.known_apps.get(normalize_exe(exe))
        name = (info or {}).get("name", "")
        return name or default_app_name(normalize_exe(exe))

    def get_enabled_rules(self) -> List[dict]:
        return [r for r in self.rules if r.get("enabled", True)]

    # ------------------------------------------------------- source apps

    def note_source_app(self, exe: str, name: str = "", path: str = "") -> None:
        """Remember an app a link came from (or one picked in the rule
        editor). Saved only when the app is new or its name/path changed;
        last_seen alone rides along with the next save."""
        exe = normalize_exe(exe)
        if not exe:
            return
        info = self.known_apps.get(exe)
        changed = info is None
        info = info or {}
        if name and info.get("name") != name:
            info["name"] = name
            changed = True
        if path and info.get("path") != path:
            info["path"] = path
            changed = True
        info["last_seen"] = int(time.time())
        self.known_apps[exe] = info
        if changed:
            self.save()

    # ---------------------------------------------------------- rule helpers

    def add_quick_rule(self, hostname: str, browser_id: str,
                       private: bool = False) -> Tuple[dict, bool]:
        """Create (or update) the single-hostname rule made by press-and-hold.
        Returns (rule, created). An existing open rule whose only condition is
        the same exact hostname (and that has no source filter) is retargeted
        instead of duplicated. Either way the rule moves to the TOP of the
        list, so it wins ties against other exact-hostname rules for the same
        site: the latest explicit choice is the one that applies."""
        for i, r in enumerate(self.rules):
            conds = r.get("conditions", [])
            if (r.get("action", ACTION_OPEN) == ACTION_OPEN and len(conds) == 1
                    and not r.get("source_apps")
                    and conds[0].get("match_type") == "exact_hostname"
                    and conds[0].get("pattern", "").lower() == hostname.lower()):
                r.update({"enabled": True, "browser_id": browser_id, "private": private})
                self.rules.insert(0, self.rules.pop(i))
                self.save()
                return r, False
        rule = {
            "id": str(uuid.uuid4()),
            "enabled": True,
            "name": "",
            "action": ACTION_OPEN,
            "conditions": [{"match_type": "exact_hostname", "pattern": hostname}],
            "source_apps": [],
            "source_except": False,
            "browser_id": browser_id,
            "private": private,
            "browsers": [],
        }
        self.rules.insert(0, rule)
        self.save()
        return rule, True

    def delete_rule(self, rule_id: str) -> None:
        self._data["rules"] = [r for r in self._data["rules"] if r.get("id") != rule_id]
        self.save()
