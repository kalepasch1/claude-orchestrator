#!/usr/bin/env python3
"""
cx_determination_drift.py - sample older determinations, replay them on today's evidence, and surface
drift so stale rulings do not silently keep governing behavior.

The replay path is treated as read-only here. committees.replay_determination() reuses the full review
machinery, which can append committee trail rows; this runner suppresses those writes during replay and
only writes the final inbox alert when drift is detected.
"""
import datetime
import os
import sys
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import committees
import db

replay_determination = committees.replay_determination

DEFAULT_SAMPLE_LIMIT = 12
DEFAULT_ALERT_LIMIT = 3
DEFAULT_MIN_AGE_DAYS = 7


def _int_env(name, default, minimum=1):
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except Exception:
        return default


def _cutoff(days):
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return dt.isoformat(timespec="seconds")


def _pick_determinations(limit, min_age_days):
    """Return a bounded, oldest-first sample with enough fields to skip empty determinations."""
    try:
        rows = db.select("determinations", {
            "select": "id,title,body,recommendation,consensus_pct,created_at",
            "recommendation": "not.is.null",
            "created_at": f"lt.{_cutoff(min_age_days)}",
            "order": "created_at.asc",
            "limit": str(limit),
        }) or []
    except Exception:
        return []
    out = []
    for row in rows:
        if row.get("id") and (row.get("title") or row.get("body")):
            out.append(row)
    return out


@contextmanager
def _readonly_committee_replay():
    """Suppress committee persistence during replay; alerts are written after this context exits."""
    original_insert = committees.db.insert
    original_update = committees.db.update

    def _noop(*_args, **_kwargs):
        return None

    committees.db.insert = _noop
    committees.db.update = _noop
    try:
        yield
    finally:
        committees.db.insert = original_insert
        committees.db.update = original_update


def _moved(then, now):
    try:
        return abs(float(now or 0) - float(then or 0)) >= 0.1
    except Exception:
        return False


def _drifted(result):
    then = (result or {}).get("then") or {}
    now = (result or {}).get("now") or {}
    return bool(
        (result or {}).get("changed") or
        then.get("recommendation") != now.get("recommendation") or
        _moved(then.get("consensus_pct"), now.get("consensus_pct"))
    )


def _already_alerted(det_id):
    try:
        rows = db.select("inbox", {
            "select": "id",
            "kind": "eq.drift",
            "body": f"ilike.%determination_id={det_id}%",
            "limit": "1",
        }) or []
        return bool(rows)
    except Exception:
        return False


def _open_alert(det, result):
    then = result.get("then") or {}
    now = result.get("now") or {}
    title = (det.get("title") or "untitled determination")[:160]
    body = (
        f"determination_id={det.get('id')}\n"
        f"Then: {then.get('recommendation')} at consensus {then.get('consensus_pct')}\n"
        f"Now: {now.get('recommendation')} at consensus {now.get('consensus_pct')}\n"
        f"Replay note: {result.get('note') or 'drift detected'}"
    )
    db.insert("inbox", {
        "kind": "drift",
        "title": f"Determination drift: {title}",
        "body": body[:2000],
        "status": "unread",
    })


def run(sample_limit=None, alert_limit=None, min_age_days=None):
    """Replay a small sample of older determinations and open at most alert_limit drift alerts."""
    sample_limit = sample_limit or _int_env("CX_DRIFT_SAMPLE_LIMIT", DEFAULT_SAMPLE_LIMIT)
    alert_limit = alert_limit or _int_env("CX_DRIFT_ALERT_LIMIT", DEFAULT_ALERT_LIMIT)
    min_age_days = min_age_days or _int_env("CX_DRIFT_MIN_AGE_DAYS", DEFAULT_MIN_AGE_DAYS)

    opened = 0
    checked = 0
    for det in _pick_determinations(sample_limit, min_age_days):
        if opened >= alert_limit:
            break
        det_id = det.get("id")
        if _already_alerted(det_id):
            continue
        checked += 1
        try:
            with _readonly_committee_replay():
                result = replay_determination(det_id)
        except Exception:
            continue
        if result.get("error") or not _drifted(result):
            continue
        try:
            _open_alert(det, result)
            opened += 1
        except Exception:
            continue

    print(f"cx_determination_drift.run: checked {checked}, opened {opened} drift alerts")
    return opened


if __name__ == "__main__":
    run()
