#!/usr/bin/env python3
"""
error_alerter.py - notify team members when critical errors occur.

Provides alerting via multiple channels:
  1. In-app: writes structured alerts to a Supabase `alerts` table for the dashboard
  2. Email: sends via SMTP if ORCH_ALERT_EMAIL is configured
  3. Webhook: POSTs to a URL if ORCH_ALERT_WEBHOOK is configured

Deduplication: the same alert (by pattern+project) is suppressed for a configurable
cooldown window so the team isn't spammed on cascading failures.

Usage:
    import error_alerter
    error_alerter.alert("build_failure", project_id="abc", detail="OOM during nuxt build")
    error_alerter.alert("merge_blocked", project_id="abc", detail="3 tasks stuck")
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ALERT_EMAIL = os.environ.get("ORCH_ALERT_EMAIL", "")
ALERT_WEBHOOK = os.environ.get("ORCH_ALERT_WEBHOOK", "")
COOLDOWN_SECONDS = int(os.environ.get("ORCH_ALERT_COOLDOWN", "900"))  # 15 min default
ALERT_ENABLED = os.environ.get("ORCH_ALERTS_ENABLED", "true").lower() in ("1", "true", "yes")

_lock = threading.Lock()
_last_alert: dict = {}  # (pattern, project_id) -> timestamp

SEVERITY_MAP = {
    "build_failure": "warning",
    "merge_blocked": "warning",
    "fleet_down": "critical",
    "disk_full": "critical",
    "oom": "critical",
    "rate_limit": "info",
    "test_failure": "warning",
    "stuck_tasks": "warning",
}


def _should_alert(pattern: str, project_id: str) -> bool:
    """Check cooldown deduplication. Returns True if alert should fire."""
    key = (pattern, project_id)
    now = time.time()
    with _lock:
        last = _last_alert.get(key, 0)
        if now - last < COOLDOWN_SECONDS:
            return False
        _last_alert[key] = now
    return True


def alert(pattern: str, project_id: str = "", detail: str = "", severity: str = "") -> bool:
    """Fire an alert for the given pattern. Returns True if the alert was sent.

    Fail-soft: never raises. Returns False on any error or cooldown suppression.
    """
    if not ALERT_ENABLED:
        return False

    if not _should_alert(pattern, project_id):
        return False

    severity = severity or SEVERITY_MAP.get(pattern, "info")
    sent = False

    # Channel 1: In-app (Supabase alerts table)
    sent = _alert_inapp(pattern, project_id, detail, severity) or sent

    # Channel 2: Email (if configured)
    if ALERT_EMAIL:
        sent = _alert_email(pattern, project_id, detail, severity) or sent

    # Channel 3: Webhook (if configured)
    if ALERT_WEBHOOK:
        sent = _alert_webhook(pattern, project_id, detail, severity) or sent

    return sent


def _alert_inapp(pattern: str, project_id: str, detail: str, severity: str) -> bool:
    """Write alert to fleet_config for dashboard visibility. Fail-soft."""
    try:
        import db
        import json
        alert_data = json.dumps({
            "pattern": pattern,
            "project_id": project_id,
            "detail": detail[:500],
            "severity": severity,
            "ts": time.time(),
        })
        key = f"ORCH_ALERT_{pattern}_{project_id[:8] if project_id else 'global'}"
        db.query(
            "INSERT INTO fleet_config (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (key, alert_data),
        )
        return True
    except Exception:
        return False


def _alert_email(pattern: str, project_id: str, detail: str, severity: str) -> bool:
    """Send alert via SMTP. Fail-soft."""
    try:
        import smtplib
        from email.mime.text import MIMEText

        smtp_host = os.environ.get("ORCH_SMTP_HOST", "")
        smtp_port = int(os.environ.get("ORCH_SMTP_PORT", "587"))
        smtp_user = os.environ.get("ORCH_SMTP_USER", "")
        smtp_pass = os.environ.get("ORCH_SMTP_PASS", "")

        if not smtp_host or not smtp_user:
            return False

        subject = f"[{severity.upper()}] Orchestrator: {pattern}"
        body = f"Pattern: {pattern}\nProject: {project_id or 'global'}\nDetail: {detail}\nSeverity: {severity}"

        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = ALERT_EMAIL

        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
            s.starttls()
            s.login(smtp_user, smtp_pass)
            s.send_message(msg)
        return True
    except Exception:
        return False


def _alert_webhook(pattern: str, project_id: str, detail: str, severity: str) -> bool:
    """POST alert to a webhook URL. Fail-soft."""
    try:
        import urllib.request
        import json

        payload = json.dumps({
            "pattern": pattern,
            "project_id": project_id,
            "detail": detail[:500],
            "severity": severity,
            "timestamp": time.time(),
        }).encode()

        req = urllib.request.Request(
            ALERT_WEBHOOK,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        return False


def stats() -> dict:
    """Return alert dedup cache stats."""
    with _lock:
        return {
            "active_cooldowns": len(_last_alert),
            "patterns": list(set(k[0] for k in _last_alert)),
        }


def reset():
    """Clear cooldown cache (for testing)."""
    with _lock:
        _last_alert.clear()
