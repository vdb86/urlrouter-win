"""
router.py — URL routing logic.

Priority (first match wins):
  1. exact_hostname
  2. wildcard_hostname
  3. url_prefix
  4. contains
  5. regex
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

MATCH_TYPES: List[str] = [
    "exact_hostname",
    "wildcard_hostname",
    "url_prefix",
    "contains",
    "regex",
]

MATCH_TYPE_LABELS: Dict[str, str] = {
    "exact_hostname":    "Exact hostname",
    "wildcard_hostname": "Wildcard hostname",
    "url_prefix":        "URL prefix",
    "contains":          "Contains",
    "regex":             "Regex",
}

_PRIORITY = MATCH_TYPES  # same order


def route(url: str, rules: List[Dict]) -> Optional[Dict]:
    """Return the first matching rule or None."""
    enabled = [r for r in rules if r.get("enabled", True)]
    for match_type in _PRIORITY:
        for rule in enabled:
            if rule.get("match_type") == match_type and _matches(url, rule):
                return rule
    return None


def diagnose(url: str, rules: List[Dict]) -> Dict[str, Any]:
    """Return a diagnostic dict describing which rules match."""
    enabled = [r for r in rules if r.get("enabled", True)]
    results: List[Dict] = []
    first_match: Optional[Dict] = None

    for match_type in _PRIORITY:
        for rule in enabled:
            if rule.get("match_type") != match_type:
                continue
            hit = _matches(url, rule)
            results.append({"rule": rule, "matched": hit})
            if hit and first_match is None:
                first_match = rule

    return {"matched_rule": first_match, "all_results": results}


# ----------------------------------------------------------------- internals


def _matches(url: str, rule: Dict) -> bool:
    mt = rule.get("match_type", "")
    pat = rule.get("pattern", "")
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().lstrip("www.")

        if mt == "exact_hostname":
            return host == pat.lower().lstrip("www.")

        if mt == "wildcard_hostname":
            return _wildcard(host, pat.lower())

        if mt == "url_prefix":
            return url.lower().startswith(pat.lower())

        if mt == "contains":
            return pat.lower() in url.lower()

        if mt == "regex":
            return bool(re.search(pat, url, re.IGNORECASE))

    except Exception:
        pass
    return False


def _wildcard(host: str, pat: str) -> bool:
    """Match *.example.com style patterns."""
    if pat.startswith("*."):
        suffix = pat[2:]
        return host == suffix or host.endswith("." + suffix)
    return host == pat


def hostname_from_url(url: str) -> str:
    try:
        h = urlparse(url).hostname or ""
        return h.lstrip("www.")
    except Exception:
        return ""
