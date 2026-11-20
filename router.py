"""
router.py - URL routing engine (pure Python, no Qt, unit-testable).

Rule shape (config version 2)
─────────────────────────────
{
  "id":            str,
  "enabled":       bool,
  "name":          str,            # custom name; "" = automatic name
  "action":        "open" | "exclude" | "ask",
  "conditions":    [ {"match_type": str, "pattern": str}, ... ],   # OR-ed
  "source_apps":   [str, ...],     # exe names ("slack.exe"); [] = from any app
  "source_except": bool,           # True: any app EXCEPT source_apps
  "browser_id":    str,            # open: the browser to open
  "private":       bool,           # open: launch in a private window
  "browsers":      [str, ...],     # exclude: never offer these
                                   # ask:     offer only these ([] = all)
}

Conditions and the source filter
────────────────────────────────
The conditions are OR-ed: any one matching link triggers the rule. The source
apps ("Only when opened from") are a FILTER AND-ed on top. A rule with a
filter may have no conditions at all: it then matches every link from those
apps. A rule with neither never matches. When the source app is not known, a
rule with a filter is skipped in both modes (fail closed).

Decision order
──────────────
1. EXCLUDE rules are collected first. They never win; they remove browsers
   from everything below (rule targets, default fallback, chooser).
2. OPEN and ASK rules compete in one ranking, each by its best matching
   condition:
     a. parts matched: a link condition and a source filter count 1 each,
        more parts beat fewer
     b. match type: exact hostname, wildcard hostname, URL prefix,
        contains, regex; a rule with no link condition comes last
     c. longer pattern beats shorter (wildcard / prefix / contains)
     d. position in the rules list (higher = wins ties)
   So "github.com from Slack" beats "github.com", which beats "from Slack".
   An OPEN rule whose browser is excluded, disabled or missing is passed over.
   An ASK rule that wins shows the chooser.
3. The default fallback browser, unless it is excluded.
4. The chooser.

Conditions that are incomplete or unreadable never match (fail closed).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

# ------------------------------------------------------------------ constants

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

ACTION_OPEN    = "open"
ACTION_EXCLUDE = "exclude"
ACTION_ASK     = "ask"
ACTIONS: List[str] = [ACTION_OPEN, ACTION_EXCLUDE, ACTION_ASK]

ACTION_LABELS: Dict[str, str] = {
    ACTION_OPEN:    "Open in browser",
    ACTION_EXCLUDE: "Never offer",
    ACTION_ASK:     "Always ask",
}

# Match types whose specificity grows with pattern length.
_LENGTH_RANKED = {"wildcard_hostname", "url_prefix", "contains"}

# Outcome markers used in the trace.
WON       = "WON"
NO_MATCH  = "NO MATCH"
UNKNOWN   = "UNKNOWN SOURCE"
REJECTED  = "REJECTED"
EXCLUDED  = "EXCLUDES"
EMPTY     = "EMPTY"
NOTE      = "NOTE"

# evaluate_rule() results
_MATCH, _NO, _UNKNOWN = "match", "no", "unknown"

AppName = Callable[[str], str]


# ------------------------------------------------------------------ hostnames

def strip_www(host: str) -> str:
    """Remove ONE leading 'www.' (not any leading 'w' / '.' characters)."""
    return host[4:] if host.startswith("www.") else host


def hostname_from_url(url: str) -> str:
    try:
        return strip_www((urlparse(url.strip()).hostname or "").lower())
    except Exception:
        return ""


def normalize_pattern(match_type: str, pattern: str) -> str:
    """Tidy a user-entered pattern. Hostname patterns pasted as full URLs are
    reduced to their hostname; exact hostnames lose a leading 'www.'."""
    pat = (pattern or "").strip()
    if match_type in ("exact_hostname", "wildcard_hostname"):
        if "://" in pat:
            wildcard = pat.split("://", 1)[1].startswith("*.")
            host = urlparse(pat.replace("*.", "", 1) if wildcard else pat).hostname or ""
            pat = ("*." + host) if wildcard else host
        pat = pat.lower().rstrip("/")
        if match_type == "exact_hostname":
            pat = strip_www(pat)
    return pat


def validate_condition(match_type: str, pattern: str) -> Optional[str]:
    """Return an error message, or None when the condition is usable."""
    if match_type not in MATCH_TYPES:
        return f"Unknown match type {match_type!r}."
    if not (pattern or "").strip():
        return "Pattern cannot be empty."
    if match_type == "regex":
        try:
            re.compile(pattern)
        except re.error as exc:
            return f"Invalid regular expression: {exc}"
    if match_type in ("exact_hostname", "wildcard_hostname"):
        pat = pattern.strip()
        if any(ch in pat for ch in " /?#:"):
            return "A hostname cannot contain spaces, '/', '?', '#' or ':' (ports are not matched)."
        if match_type == "exact_hostname" and "*" in pat:
            return "Exact hostnames cannot contain '*'. Use Wildcard hostname for *.example.com."
        if match_type == "wildcard_hostname" and "*" in (pat[2:] if pat.startswith("*.") else pat):
            return "Use '*' only at the start, as in *.example.com."
    return None


# ------------------------------------------------------------------ source apps

def normalize_exe(name: str) -> str:
    """'C:\\...\\Slack.exe', 'Slack.exe' or 'slack' -> 'slack.exe'."""
    n = (name or "").strip().strip('"').replace("/", "\\")
    n = n.rsplit("\\", 1)[-1].strip().lower()
    if n and not os.path.splitext(n)[1]:
        n += ".exe"
    return n


def default_app_name(exe: str) -> str:
    stem = exe[:-4] if exe.lower().endswith(".exe") else exe
    return stem[:1].upper() + stem[1:] if stem else "?"


def rule_source_apps(rule: Dict) -> List[str]:
    apps = rule.get("source_apps")
    return [a for a in apps if isinstance(a, str) and a] if isinstance(apps, list) else []


def has_source_filter(rule: Dict) -> bool:
    return bool(rule_source_apps(rule))


def source_exe(source: Union[str, Dict, None]) -> str:
    """The exe name from a detected source (dict) or a plain name."""
    if isinstance(source, dict):
        source = source.get("exe", "")
    return normalize_exe(source or "")


# ------------------------------------------------------------------ matching

def condition_is_well_formed(cond: Any) -> bool:
    return (isinstance(cond, dict)
            and cond.get("match_type") in MATCH_TYPES
            and isinstance(cond.get("pattern"), str)
            and bool(cond.get("pattern", "").strip()))


def condition_matches(url: str, cond: Dict) -> bool:
    if not condition_is_well_formed(cond):
        return False
    mt  = cond["match_type"]
    pat = cond["pattern"].strip()
    try:
        if mt == "exact_hostname":
            return hostname_from_url(url) == strip_www(pat.lower())

        if mt == "wildcard_hostname":
            return _wildcard(hostname_from_url(url), pat.lower())

        if mt == "url_prefix":
            # "https://youtube.com/watch" also matches "https://www.youtube.com/watch".
            return _strip_www_after_scheme(url.lower()).startswith(
                _strip_www_after_scheme(pat.lower()))

        if mt == "contains":
            return pat.lower() in url.lower()

        if mt == "regex":
            return bool(re.search(pat, url, re.IGNORECASE))
    except Exception:
        pass
    return False


def _strip_www_after_scheme(s: str) -> str:
    scheme, sep, rest = s.partition("://")
    if sep and rest.startswith("www."):
        return scheme + sep + rest[4:]
    return s


def _wildcard(host: str, pat: str) -> bool:
    """Match '*.example.com' (example.com and any subdomain)."""
    if not host:
        return False
    if pat.startswith("*."):
        suffix = strip_www(pat[2:])
        return host == suffix or host.endswith("." + suffix)
    return host == strip_www(pat)


def condition_rank(cond: Dict) -> Tuple[int, int]:
    """Lower sorts first = more specific."""
    mt   = cond.get("match_type", "")
    tier = MATCH_TYPES.index(mt) if mt in MATCH_TYPES else len(MATCH_TYPES)
    length = len(cond.get("pattern", "").strip()) if mt in _LENGTH_RANKED else 0
    return (tier, -length)


def match_rank(rule: Dict, cond: Optional[Dict]) -> Tuple[int, int, int]:
    """Rank of a rule matched through `cond` (None = no link condition, the
    rule matched by its source filter alone). Lower sorts first."""
    parts = (1 if cond else 0) + (1 if has_source_filter(rule) else 0)
    tier, neg_len = condition_rank(cond) if cond else (len(MATCH_TYPES), 0)
    return (-parts, tier, neg_len)


def rule_conditions(rule: Dict) -> List[Dict]:
    conds = rule.get("conditions")
    return conds if isinstance(conds, list) else []


def best_matching_condition(url: str, rule: Dict) -> Optional[Dict]:
    hits = [c for c in rule_conditions(rule) if condition_matches(url, c)]
    return min(hits, key=condition_rank) if hits else None


def rule_static_rank(rule: Dict) -> Tuple[int, int, int]:
    """Rank of a rule's most specific condition, for lists."""
    conds = [c for c in rule_conditions(rule) if condition_is_well_formed(c)]
    if not conds:
        return match_rank(rule, None) if has_source_filter(rule) else (0, 99, 0)
    return min(match_rank(rule, c) for c in conds)


def evaluate_rule(url: str, rule: Dict, src: str,
                  app_name: Optional[AppName] = None) -> Tuple[str, Optional[Dict], str]:
    """Test one rule: the source filter first, then the conditions.
    Returns (result, matched condition or None, reason)."""
    apps = rule_source_apps(rule)
    if apps:
        if not src:
            return (_UNKNOWN, None,
                    f"is only for links {describe_source(rule, app_name)}, "
                    "but the app the link came from is not known")
        listed = src in apps
        name = app_name or default_app_name
        if rule.get("source_except") and listed:
            return _NO, None, f"leaves out links from {name(src)}"
        if not rule.get("source_except") and not listed:
            return (_NO, None,
                    f"is for links {describe_source(rule, app_name)}, "
                    f"this came from {name(src)}")
    if not rule_conditions(rule):
        if apps:
            return _MATCH, None, ""
        return _NO, None, "has no conditions"
    cond = best_matching_condition(url, rule)
    if cond is None:
        return _NO, None, ""
    return _MATCH, cond, ""


# ------------------------------------------------------------------ naming

def describe_condition(cond: Dict) -> str:
    mt  = cond.get("match_type", "")
    pat = cond.get("pattern", "")
    if mt in ("exact_hostname", "wildcard_hostname"):
        return pat
    if mt == "url_prefix":
        return f"links starting with {pat}"
    if mt == "contains":
        return f"links containing '{pat}'"
    if mt == "regex":
        return f"links matching /{pat}/"
    return pat or "?"


def describe_conditions(rule: Dict) -> str:
    conds = rule_conditions(rule)
    if not conds:
        return "any link" if has_source_filter(rule) else "nothing"
    return " or ".join(describe_condition(c) for c in conds)


def describe_source(rule: Dict, app_name: Optional[AppName] = None) -> str:
    """'from Slack or Discord', 'not from Slack', or '' with no filter."""
    apps = rule_source_apps(rule)
    if not apps:
        return ""
    name = app_name or default_app_name
    names = " or ".join(name(a) for a in apps)
    return f"not from {names}" if rule.get("source_except") else f"from {names}"


def describe_when(rule: Dict, app_name: Optional[AppName] = None) -> str:
    """Conditions plus source filter, for names and tooltips."""
    what = describe_conditions(rule) if rule_conditions(rule) else "links"
    src = describe_source(rule, app_name)
    return f"{what} {src}" if src else what


def auto_rule_name(rule: Dict, browser_name: Callable[[str], str],
                   app_name: Optional[AppName] = None) -> str:
    what   = describe_when(rule, app_name)
    action = rule.get("action", ACTION_OPEN)
    names  = [browser_name(b) for b in rule.get("browsers", []) or []]
    if action == ACTION_EXCLUDE:
        return f"Never offer {', '.join(names) or '?'} for {what}"
    if action == ACTION_ASK:
        only = f", offering only {', '.join(names)}" if names else ""
        return f"Always ask for {what}{only}"
    target = browser_name(rule.get("browser_id", "")) or "?"
    private = " (private)" if rule.get("private") else ""
    return f"{what} → {target}{private}"


def rule_display_name(rule: Dict, browser_name: Callable[[str], str],
                      app_name: Optional[AppName] = None) -> str:
    custom = (rule.get("name") or "").strip()
    return custom or auto_rule_name(rule, browser_name, app_name)


# ------------------------------------------------------------------ decision

@dataclass
class TraceStep:
    stage: str
    outcome: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.stage}] {self.outcome}: {self.detail}"


@dataclass
class Decision:
    # "open"    - launch `browser` (a rule won)
    # "default" - launch `browser` (default fallback)
    # "ask"     - show the chooser with `offered` (an "Always ask" rule won)
    # "chooser" - show the chooser with `offered` (nothing decided)
    action: str
    browser: Optional[Dict] = None
    private: bool = False
    rule: Optional[Dict] = None
    offered: List[Dict] = field(default_factory=list)
    excluded: Dict[str, Dict] = field(default_factory=dict)   # browser_id → rule
    trace: List[TraceStep] = field(default_factory=list)


def decide(url: str, rules: List[Dict], browsers: List[Dict],
           source: Union[str, Dict, None] = None,
           app_name: Optional[AppName] = None) -> Decision:
    """`source` is the app the link came from: a detected source dict, an exe
    name, or None when not known."""
    trace: List[TraceStep] = []
    enabled_browsers = [b for b in browsers if b.get("enabled", True)]
    by_id = {b.get("id"): b for b in browsers}
    src = source_exe(source)
    aname = app_name or default_app_name

    def bname(bid: str) -> str:
        b = by_id.get(bid)
        return b.get("name", bid) if b else (bid or "?")

    def rlabel(rule: Dict) -> str:
        return f'"{rule_display_name(rule, bname, aname)}"'

    def unmatched(stage: str, rule: Dict, result: str, reason: str) -> None:
        outcome = UNKNOWN if result == _UNKNOWN else NO_MATCH
        trace.append(TraceStep(stage, outcome,
                               f"{rlabel(rule)}: {reason}" if reason else rlabel(rule)))

    def how(rule: Dict, cond: Optional[Dict]) -> str:
        parts = []
        if cond:
            parts.append(f"{MATCH_TYPE_LABELS.get(cond['match_type'], '?')} {cond['pattern']!r}")
        if has_source_filter(rule):
            parts.append(describe_source(rule, aname))
        return " AND ".join(parts) or "?"

    trace.append(TraceStep("source", NOTE,
                           f"link came from {aname(src)} ({src})" if src
                           else "the app the link came from is not known"))

    active = [(i, r) for i, r in enumerate(rules) if r.get("enabled", True)]

    # ---- 1. Excludes ------------------------------------------------------
    excluded: Dict[str, Dict] = {}
    exclude_rules = [(i, r) for i, r in active if r.get("action") == ACTION_EXCLUDE]
    for _, rule in exclude_rules:
        result, _cond, reason = evaluate_rule(url, rule, src, aname)
        if result != _MATCH:
            unmatched("exclude", rule, result, reason)
            continue
        ids = [b for b in rule.get("browsers", []) or [] if b]
        for bid in ids:
            excluded.setdefault(bid, rule)
        trace.append(TraceStep(
            "exclude", EXCLUDED,
            f"{rlabel(rule)} hides {', '.join(bname(b) for b in ids) or 'nothing'}"
        ))
    if not exclude_rules:
        trace.append(TraceStep("exclude", EMPTY, "no exclude rules"))

    def offer(candidates: List[Dict]) -> List[Dict]:
        kept = [b for b in candidates if b.get("id") not in excluded]
        if not kept and candidates:
            trace.append(TraceStep(
                "chooser", NOTE,
                "every browser would be hidden, so all are offered instead"
            ))
            return list(candidates)
        return kept

    # ---- 2. Open / Ask rules ---------------------------------------------
    ranked: List[Tuple[Tuple, int, Dict, Optional[Dict]]] = []
    competing = [(i, r) for i, r in active
                 if r.get("action", ACTION_OPEN) in (ACTION_OPEN, ACTION_ASK)]
    for pos, rule in competing:
        result, cond, reason = evaluate_rule(url, rule, src, aname)
        if result != _MATCH:
            unmatched("rule", rule, result, reason)
            continue
        ranked.append((match_rank(rule, cond), pos, rule, cond))
    ranked.sort(key=lambda t: (t[0], t[1]))

    for _, _, rule, cond in ranked:
        matched_by = how(rule, cond)
        if rule.get("action") == ACTION_ASK:
            only = [b for b in rule.get("browsers", []) or []]
            pool = ([b for b in enabled_browsers if b.get("id") in only]
                    if only else enabled_browsers)
            if only and not pool:
                trace.append(TraceStep(
                    "rule", NOTE,
                    f"{rlabel(rule)}: none of its browsers is enabled, offering all"
                ))
                pool = enabled_browsers
            offered = offer(pool)
            trace.append(TraceStep("rule", WON,
                                   f"{rlabel(rule)} matched ({matched_by}): always ask"))
            return Decision("ask", rule=rule, offered=offered,
                            excluded=excluded, trace=trace)

        bid = rule.get("browser_id", "")
        browser = by_id.get(bid)
        if browser is None:
            trace.append(TraceStep("rule", REJECTED,
                                   f"{rlabel(rule)} matched but its browser is missing"))
            continue
        if not browser.get("enabled", True):
            trace.append(TraceStep("rule", REJECTED,
                                   f"{rlabel(rule)} matched but {bname(bid)} is disabled"))
            continue
        if bid in excluded:
            trace.append(TraceStep(
                "rule", REJECTED,
                f"{rlabel(rule)} matched but {bname(bid)} is hidden by {rlabel(excluded[bid])}"
            ))
            continue
        private = bool(rule.get("private", False))
        trace.append(TraceStep(
            "rule", WON,
            f"{rlabel(rule)} matched ({matched_by}): open {bname(bid)}"
            + (" in a private window" if private else "")
        ))
        return Decision("open", browser=browser, private=private, rule=rule,
                        excluded=excluded, trace=trace)
    if not competing:
        trace.append(TraceStep("rule", EMPTY, "no open / always-ask rules"))

    # ---- 3. Default fallback ---------------------------------------------
    default = next((b for b in enabled_browsers if b.get("is_default_fallback")), None)
    if default is None:
        trace.append(TraceStep("default", EMPTY, "no default fallback browser"))
    elif default.get("id") in excluded:
        trace.append(TraceStep(
            "default", REJECTED,
            f"{bname(default['id'])} is hidden by {rlabel(excluded[default['id']])}"
        ))
    else:
        trace.append(TraceStep("default", WON, f"open {bname(default['id'])}"))
        return Decision("default", browser=default, excluded=excluded, trace=trace)

    # ---- 4. Chooser -------------------------------------------------------
    offered = offer(enabled_browsers)
    trace.append(TraceStep("chooser", WON,
                           f"show the chooser with {len(offered)} browser(s)"))
    return Decision("chooser", offered=offered, excluded=excluded, trace=trace)


# ------------------------------------------------------------------ migration

def normalize_rule(rule: Any) -> Optional[Dict]:
    """Bring a rule (version 1 or 2) to the version 2 shape. None if unusable."""
    if not isinstance(rule, dict):
        return None
    import uuid
    apps: List[str] = []
    raw_apps = rule.get("source_apps")
    for a in raw_apps if isinstance(raw_apps, list) else []:
        exe = normalize_exe(str(a)) if a else ""
        if exe and exe not in apps:
            apps.append(exe)
    out: Dict[str, Any] = {
        "id":            str(rule.get("id") or uuid.uuid4()),
        "enabled":       bool(rule.get("enabled", True)),
        "name":          str(rule.get("name") or ""),
        "action":        rule.get("action") if rule.get("action") in ACTIONS else ACTION_OPEN,
        "conditions":    [],
        "source_apps":   apps,
        "source_except": bool(rule.get("source_except", False)) and bool(apps),
        "browser_id":    str(rule.get("browser_id") or ""),
        "private":       bool(rule.get("private", False)),
        "browsers":      [str(b) for b in (rule.get("browsers") or []) if b],
    }
    conds = rule.get("conditions")
    if isinstance(conds, list):
        out["conditions"] = [
            {"match_type": c.get("match_type", ""), "pattern": str(c.get("pattern", ""))}
            for c in conds if isinstance(c, dict)
        ]
    elif "match_type" in rule:                       # version 1
        out["conditions"] = [{"match_type": rule.get("match_type", ""),
                              "pattern": str(rule.get("pattern", ""))}]
    return out
