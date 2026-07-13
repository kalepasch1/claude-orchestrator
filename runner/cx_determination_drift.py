#!/usr/bin/env python3
"""
cx_determination_drift.py - detect stale determinations whose verdict no longer holds.

Periodically samples a small, bounded number of OLDER determinations and replays each one
against today's evidence via committees.replay_determination (no schema change, no edits to
committees.py). If the replay's recommendation flipped, or its consensus score moved by >= 0.1
vs. the originally recorded determination, opens an inbox alert (kind='drift') so a reviewer
knows a past call may no longer hold.

Read-only aside from the inbox alert and a determination_outcomes marker row used to avoid
re-checking the same determination every run. Never mutates the original determination record.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import committees

MAX_PER_RUN = int(os.environ.get("CX_DRIFT_MAX", "3"))
CONSENSUS_DRIFT_THRESHOLD = 0.1


def _already_checked_ids():
    """Determination ids already replayed for drift, so we don't recheck every run."""
    out = set()
    for r in (db.select("determination_outcomes", {
        "select": "subject_id", "source": "eq.determination_drift",
    }) or []):
        sid = r.get("subject_id")
        if sid:
            out.add(sid)
    return out


def _sample_older_determinations():
    """Sample a small, bounded number of the oldest not-yet-rechecked determinations."""
    checked = _already_checked_ids()
    dets = db.select("determinations", {
        "select": "id,title,recommendation,consensus_pct,app",
        "order": "created_at.asc",
        "limit": str(MAX_PER_RUN * 5),
    }) or []
    candidates = [d for d in dets if d.get("id") not in checked]
    return candidates[:MAX_PER_RUN]


def run():
    """Main entry point. Bounded to MAX_PER_RUN determinations per run."""
    candidates = _sample_older_determinations()
    if not candidates:
        print("cx_determination_drift: no eligible determinations, skipping")
        return {"checked": 0, "drifted": 0}

    checked = 0
    drifted = 0

    for d in candidates:
        det_id = d.get("id")
        if not det_id:
            continue
        try:
            replay = committees.replay_determination(det_id)
            if not replay or replay.get("error"):
                continue
            checked += 1

            then = replay.get("then") or {}
            now = replay.get("now") or {}
            rec_changed = then.get("recommendation") != now.get("recommendation")
            consensus_moved = round(abs(float(now.get("consensus_pct") or 0)
                                        - float(then.get("consensus_pct") or 0)), 6) >= CONSENSUS_DRIFT_THRESHOLD

            # Mark this determination as checked so future runs don't re-sample it.
            try:
                db.insert("determination_outcomes", {
                    "determination_id": det_id,
                    "subject_id": det_id,
                    "metric": "drift_check",
                    "source": "determination_drift",
                    "detail": json.dumps({"then": then, "now": now})[:2000],
                })
            except Exception:
                pass

            if rec_changed or consensus_moved:
                drifted += 1
                title = f"Drift: {(d.get('title') or det_id)[:80]}"
                body = (
                    f"Then: {then.get('recommendation')} (consensus {then.get('consensus_pct')}). "
                    f"Now: {now.get('recommendation')} (consensus {now.get('consensus_pct')}). "
                    f"{replay.get('note') or ''}"
                )
                try:
                    db.insert("inbox", {
                        "kind": "drift",
                        "title": title,
                        "body": body[:1000],
                        "app": d.get("app"),
                        "status": "unread",
                    })
                except Exception:
                    pass
        except Exception as e:
            print(f"cx_determination_drift: error replaying {det_id}: {e}")
            continue

    print(f"cx_determination_drift: checked {checked}, drifted {drifted}")
    return {"checked": checked, "drifted": drifted}


if __name__ == "__main__":
    run()
