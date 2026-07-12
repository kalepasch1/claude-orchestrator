#!/usr/bin/env python3
"""
reset_scheduler.py - time-aware account scheduling for the orchestrator.

Parses limit-banner text (e.g. "resets Jul 8 at 6am") captured in outcomes into
per-account reset timestamps. Provides claim-time hooks:

  - When an account is within N hours of reset with budget exhausted, material/Claude-tier
    tasks defer (stay QUEUED) while easy work keeps flowing to local models.
  - Immediately after a reset, temporarily raise the Claude share to burn fresh budget
    on the material backlog.
  - Overnight window (env ORCH_NIGHT_LOCAL_START/END): easy-offload share forced to 1.0.

All decisions are logged to the scoreboard.
"""
from __future__ import annotations

import os
import re
import time
import json
import datetime
from typing import Dict, Optional, Tuple

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
RESET_STATE_FILE = os.path.join(HOME, "reset_schedule_state.json")

# How many hours before a reset to start deferring material tasks
DEFER_WINDOW_HOURS = int(os.environ.get("ORCH_DEFER_WINDOW_HOURS", "4"))
# How many hours after a reset to boost Claude share
BOOST_WINDOW_HOURS = int(os.environ.get("ORCH_BOOST_WINDOW_HOURS", "2"))
# Boosted Claude share (0.0-1.0) during the post-reset window
BOOST_CLAUDE_SHARE = float(os.environ.get("ORCH_BOOST_CLAUDE_SHARE", "0.8"))
# Normal Claude share
NORMAL_CLAUDE_SHARE = float(os.environ.get("ORCH_NORMAL_CLAUDE_SHARE", "0.5"))
# Overnight local-only window (24h format)
NIGHT_LOCAL_START = int(os.environ.get("ORCH_NIGHT_LOCAL_START", "22"))
NIGHT_LOCAL_END = int(os.environ.get("ORCH_NIGHT_LOCAL_END", "6"))

# Banner patterns
_RESET_DATE_RX = re.compile(
    r"resets?\s+(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2})\s+at\s+"
    r"(?P<hour>\d{1,2})(?::(?P<min>\d{2}))?\s*(?P<ampm>[AaPp][Mm])?",
    re.I,
)
_RESET_HOURS_RX = re.compile(r"resets?\s+in\s+(?P<hours>\d+)\s+hours?", re.I)

MONTH_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def parse_reset_banner(text: str, now: Optional[datetime.datetime] = None) -> Optional[datetime.datetime]:
    """Parse a limit-banner string into a reset datetime.
    Supports: "resets Jul 8 at 6am", "resets July 8 at 6:00 AM", "resets in 3 hours".
    Returns None if no pattern matches.
    """
    if not text:
        return None
    now = now or datetime.datetime.now()
    m = _RESET_DATE_RX.search(text)
    if m:
        month = MONTH_MAP.get(m.group("month").lower())
        if month is None:
            return None
        day = int(m.group("day"))
        hour = int(m.group("hour"))
        minute = int(m.group("min") or 0)
        ampm = (m.group("ampm") or "").lower()
        if ampm == "pm" and hour != 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        year = now.year
        try:
            reset = datetime.datetime(year, month, day, hour, minute)
        except ValueError:
            return None
        if reset < now:
            try:
                reset = datetime.datetime(year + 1, month, day, hour, minute)
            except ValueError:
                return None
        return reset
    m = _RESET_HOURS_RX.search(text)
    if m:
        return now + datetime.timedelta(hours=int(m.group("hours")))
    return None


def _load_state() -> Dict:
    try:
        with open(RESET_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: Dict) -> None:
    try:
        os.makedirs(os.path.dirname(RESET_STATE_FILE), exist_ok=True)
        with open(RESET_STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception:
        pass


def record_reset_banner(account_name: str, banner_text: str,
                        now: Optional[datetime.datetime] = None) -> Optional[datetime.datetime]:
    """Parse a banner and record the reset timestamp for an account."""
    reset_dt = parse_reset_banner(banner_text, now=now)
    if reset_dt is None:
        return None
    state = _load_state()
    acct_state = state.setdefault(account_name, {})
    acct_state["reset_at"] = reset_dt.isoformat()
    acct_state["banner"] = banner_text
    acct_state["recorded_at"] = (now or datetime.datetime.now()).isoformat()
    _save_state(state)
    return reset_dt


def get_account_reset(account_name: str) -> Optional[datetime.datetime]:
    """Return the known reset datetime for an account, or None."""
    state = _load_state()
    iso = state.get(account_name, {}).get("reset_at")
    if iso:
        try:
            return datetime.datetime.fromisoformat(iso)
        except Exception:
            pass
    return None


def is_night_window(now: Optional[datetime.datetime] = None) -> bool:
    """True if current time is in the overnight local-only window."""
    hour = (now or datetime.datetime.now()).hour
    if NIGHT_LOCAL_START > NIGHT_LOCAL_END:
        return hour >= NIGHT_LOCAL_START or hour < NIGHT_LOCAL_END
    return NIGHT_LOCAL_START <= hour < NIGHT_LOCAL_END


def hours_until_reset(account_name: str, now: Optional[datetime.datetime] = None) -> Optional[float]:
    """Hours until the account's known reset, or None if unknown."""
    reset_dt = get_account_reset(account_name)
    if reset_dt is None:
        return None
    now = now or datetime.datetime.now()
    return (reset_dt - now).total_seconds() / 3600.0


def hours_since_reset(account_name: str, now: Optional[datetime.datetime] = None) -> Optional[float]:
    """Hours since the account's known reset (None if not yet reset)."""
    reset_dt = get_account_reset(account_name)
    if reset_dt is None:
        return None
    now = now or datetime.datetime.now()
    delta = (now - reset_dt).total_seconds() / 3600.0
    return delta if delta >= 0 else None


def should_defer_task(account_name: str, task_kind: str, is_exhausted: bool,
                      now: Optional[datetime.datetime] = None) -> Tuple[bool, str]:
    """Decide whether a task should be deferred based on reset timing.
    Returns (should_defer, reason).
    """
    now = now or datetime.datetime.now()
    material_kinds = {"build", "security", "hard", "legal", "plan"}
    if is_night_window(now):
        return True, "night_window"
    if is_exhausted and task_kind in material_kinds:
        h = hours_until_reset(account_name, now)
        if h is not None and 0 < h <= DEFER_WINDOW_HOURS:
            return True, f"defer_near_reset ({h:.1f}h until reset)"
    return False, ""


def get_claude_share(account_name: str, now: Optional[datetime.datetime] = None) -> float:
    """Return recommended Claude share (0.0-1.0) based on reset timing.
    Night window: 0.0. Post-reset boost: BOOST_CLAUDE_SHARE. Normal: NORMAL_CLAUDE_SHARE.
    """
    now = now or datetime.datetime.now()
    if is_night_window(now):
        return 0.0
    since = hours_since_reset(account_name, now)
    if since is not None and 0 <= since <= BOOST_WINDOW_HOURS:
        return BOOST_CLAUDE_SHARE
    return NORMAL_CLAUDE_SHARE


def log_decision(account_name: str, task_slug: str, decision: str,
                 reason: str, claude_share: float) -> None:
    """Log a scheduling decision to the scoreboard. Best-effort."""
    try:
        import db
        db.insert("scoreboard_log", {
            "account": account_name,
            "task_slug": task_slug,
            "decision": decision,
            "reason": reason,
            "claude_share": claude_share,
        })
    except Exception:
        pass
