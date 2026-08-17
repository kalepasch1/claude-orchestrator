#!/usr/bin/env python3
"""
heartbeat_monitor.py - dead-man alert: if no heartbeat from any runner for 15 minutes,
send a notification so the owner knows the fleet is down. This runs every 15 minutes;
a missed heartbeat means the heartbeat writer died silently while jobs kept running.
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

HEARTBEAT_TTL_S = 900  # 15 minutes
ALERT_AUDIENCE = os.environ.get("HEARTBEAT_ALERT_EMAIL", "kalepasch@gmail.com")


def run():
    try:
        now = datetime.datetime.now(datetime.timezone.utc)

        # Get the most recent heartbeat from any runner
        hbs = db.select("runner_heartbeats", {
            "select": "runner_id,hostname,last_seen,active_tasks",
            "order": "last_seen.desc",
            "limit": "1"
        }) or []

        if not hbs:
            # No heartbeats at all — fleet is down
            _alert("No heartbeats recorded (fleet down?)")
            return

        latest_hb = hbs[0]
        last_seen_str = latest_hb.get("last_seen")
        if not last_seen_str:
            _alert("Latest heartbeat missing last_seen timestamp")
            return

        try:
            last_seen = datetime.datetime.fromisoformat(last_seen_str.replace("Z", "+00:00"))
        except Exception as e:
            _alert(f"Could not parse last_seen timestamp: {e}")
            return

        age_s = (now - last_seen).total_seconds()
        if age_s > HEARTBEAT_TTL_S:
            # Heartbeat is stale
            runner_id = latest_hb.get("runner_id") or "unknown"
            hostname = latest_hb.get("hostname") or "unknown"
            msg = f"Fleet heartbeat stale for {int(age_s/60)} min — runner {runner_id} on {hostname} stopped updating"
            _alert(msg)
    except Exception as e:
        print(f"heartbeat_monitor error: {e}")


def _alert(message):
    """Send a dead-man alert notification."""
    try:
        # Check if we already sent an alert recently (within 15 min)
        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=HEARTBEAT_TTL_S)).isoformat().replace("+00:00", "Z")
        recent = db.select("notifications", {
            "select": "id",
            "channel": "eq.email",
            "kind": "eq.heartbeat_alert",
            "created_at": f"gte.{cutoff}",
            "limit": "1"
        }) or []

        if recent:
            # Already sent a recent alert; skip to avoid spam
            return

        # Create the alert notification
        db.insert("notifications", {
            "channel": "email",
            "audience": ALERT_AUDIENCE,
            "kind": "heartbeat_alert",
            "title": "Fleet Heartbeat Dead-Man Alert",
            "body": message,
            "sent": False
        })
        print(f"heartbeat_monitor: sent alert — {message}")
    except Exception as e:
        print(f"heartbeat_monitor: could not send alert: {e}")


if __name__ == "__main__":
    run()
