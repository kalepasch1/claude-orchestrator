#!/usr/bin/env python3
"""
realtime_approval_monitor.py - Supabase-backed approval monitoring.

Watches for new approval requests via Supabase realtime subscription
(with polling fallback every 5 min). On new approval: checks automated
approval rules, notifies if manual review is needed.

Env vars:
    ORCH_REALTIME_MONITOR_ENABLED   "false" (default) = feature flag
    ORCH_RTMON_POLL_INTERVAL        polling fallback interval in seconds (default: 300)
    ORCH_RTMON_AUTO_RULES_ENABLED   "true" (default) = apply automated approval rules
    ORCH_RTMON_NOTIFY_CHANNEL       notification channel (default: "approvals")
"""
import os, sys, time, threading, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("realtime_approval_monitor")
import db

ENABLED = os.environ.get("ORCH_REALTIME_MONITOR_ENABLED", "false").lower() in ("1", "true", "yes", "on")
POLL_INTERVAL = int(os.environ.get("ORCH_RTMON_POLL_INTERVAL", "300"))
AUTO_RULES_ENABLED = os.environ.get("ORCH_RTMON_AUTO_RULES_ENABLED", "true").lower() in ("1", "true", "yes", "on")
NOTIFY_CHANNEL = os.environ.get("ORCH_RTMON_NOTIFY_CHANNEL", "approvals")

_monitor_thread = None
_stop_event = threading.Event()
_subscription = None

_stats = {
    "started": False,
    "polls": 0,
    "approvals_checked": 0,
    "auto_approved": 0,
    "manual_flagged": 0,
    "errors": 0,
    "last_poll": None,
    "realtime_events": 0,
}

# Automated approval rules: list of (match_fn, action) pairs.
# Each match_fn takes a card dict and returns True if the rule applies.
AUTO_APPROVE_RULES = [
    # Auto-approve non-legal, non-secret, non-alarm cards
    lambda card: card.get("kind") not in ("legal", "secret") and card.get("status") == "pending",
]

ALARM_PATTERNS = [
    "key leak", "secret leak", "credential compromis",
    "billing firewall", "spend circuit",
]


def stats():
    """Return a copy of runtime statistics."""
    return dict(_stats)


def _is_alarm(card):
    """Check if a card matches alarm patterns (should never be auto-approved)."""
    text = " ".join(str(v) for v in [card.get("title", ""), card.get("why", ""), card.get("value", "")])
    text_lower = text.lower()
    return any(p in text_lower for p in ALARM_PATTERNS)


def _check_auto_rules(card):
    """Check if a card can be automatically approved based on rules.
    Returns ('auto_approve', reason) or ('manual', reason)."""
    if not AUTO_RULES_ENABLED:
        return "manual", "auto-rules disabled"
    if _is_alarm(card):
        return "manual", "alarm pattern detected"
    if card.get("kind") == "secret":
        return "manual", "secret cards require human review"
    if card.get("kind") == "legal" and card.get("legal_risk_level") == "novel":
        return "manual", "novel legal issue requires human review"
    for rule_fn in AUTO_APPROVE_RULES:
        try:
            if rule_fn(card):
                return "auto_approve", "matched auto-approve rule"
        except Exception:
            pass
    return "manual", "no auto-approve rule matched"


def _process_approval(card):
    """Process a single approval request."""
    card_id = card.get("id", "?")
    action, reason = _check_auto_rules(card)
    _stats["approvals_checked"] += 1

    if action == "auto_approve":
        try:
            db.update("approvals", {"id": card_id}, {
                "status": "approved",
                "decided_by": "auto-rtmon",
                "decided_at": "now()",
                "note": f"rtmon auto-approve: {reason}",
            })
            _stats["auto_approved"] += 1
            _log.info("auto-approved card %s: %s", card_id, reason)
        except Exception as e:
            _log.warning("failed to auto-approve card %s: %s", card_id, e)
            _stats["errors"] += 1
    else:
        _stats["manual_flagged"] += 1
        _log.info("card %s flagged for manual review: %s", card_id, reason)
        try:
            db.update("approvals", {"id": card_id}, {
                "note": f"rtmon: needs manual review ({reason})",
            })
        except Exception as e:
            _log.warning("failed to flag card %s: %s", card_id, e)
            _stats["errors"] += 1


def check_pending_approvals():
    """Poll-based check for pending approval requests. Returns count processed."""
    try:
        cards = db.select("approvals", {
            "select": "*",
            "status": "eq.pending",
            "order": "created_at.asc",
            "limit": "50",
        }) or []
    except Exception as e:
        _log.warning("failed to fetch pending approvals: %s", e)
        _stats["errors"] += 1
        return 0

    _stats["polls"] += 1
    _stats["last_poll"] = time.time()

    processed = 0
    for card in cards:
        _process_approval(card)
        processed += 1

    if processed:
        _log.info("poll: processed %d pending approvals", processed)
    return processed


def _realtime_callback(payload):
    """Handle a realtime event from Supabase subscription."""
    _stats["realtime_events"] += 1
    try:
        record = payload.get("record") or payload.get("new", {})
        if record and record.get("status") == "pending":
            _process_approval(record)
    except Exception as e:
        _log.warning("realtime callback error: %s", e)
        _stats["errors"] += 1


def _monitor_loop():
    """Background thread: subscribe to realtime if available, fall back to polling."""
    _log.info("realtime approval monitor started")
    _stats["started"] = True

    # Attempt Supabase realtime subscription
    global _subscription
    try:
        if hasattr(db, "subscribe"):
            _subscription = db.subscribe("approvals", _realtime_callback)
            _log.info("subscribed to approvals realtime channel")
    except Exception as e:
        _log.warning("realtime subscription not available, using polling only: %s", e)

    # Polling fallback loop
    while not _stop_event.is_set():
        try:
            check_pending_approvals()
        except Exception as e:
            _log.warning("poll error: %s", e)
            _stats["errors"] += 1
        _stop_event.wait(POLL_INTERVAL)


def start_monitor():
    """Start the background monitoring thread."""
    global _monitor_thread
    if not ENABLED:
        _log.info("realtime approval monitor: disabled (set ORCH_REALTIME_MONITOR_ENABLED=true)")
        return False
    if _monitor_thread and _monitor_thread.is_alive():
        _log.info("monitor already running")
        return True
    _stop_event.clear()
    _monitor_thread = threading.Thread(target=_monitor_loop, daemon=True, name="rtmon")
    _monitor_thread.start()
    _log.info("realtime approval monitor thread started")
    return True


def stop_monitor():
    """Stop the background monitoring thread."""
    global _monitor_thread, _subscription
    _stop_event.set()
    if _subscription:
        try:
            if hasattr(db, "unsubscribe"):
                db.unsubscribe(_subscription)
        except Exception as e:
            _log.warning("error unsubscribing: %s", e)
        _subscription = None
    if _monitor_thread:
        _monitor_thread.join(timeout=5)
        _monitor_thread = None
    _stats["started"] = False
    _log.info("realtime approval monitor stopped")


def run():
    """Entry point for the periodic scheduler (polling fallback)."""
    if not ENABLED:
        return {"skipped": True, "reason": "disabled"}
    return {"processed": check_pending_approvals()}


if __name__ == "__main__":
    if ENABLED:
        start_monitor()
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            stop_monitor()
    else:
        print("realtime approval monitor disabled (set ORCH_REALTIME_MONITOR_ENABLED=true)")
