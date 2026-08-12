#!/usr/bin/env python3
"""
knowledge_bus.py - cross-app knowledge sharing bus. Lets task outcomes, patterns, and
learnings from one project propagate to others without manual copy-paste.

Publishes events (task completions, error patterns, successful fixes) to a shared
knowledge_events table. Consumers in other projects can subscribe to relevant topics
and apply learnings (e.g. a fix pattern that worked in project A gets suggested in project B).

Thread-safe. Fail-soft: silently drops events on DB errors.
"""
import os, sys, time, json, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MAX_BODY_LEN = int(os.environ.get("KNOWLEDGE_BUS_MAX_BODY", "4000"))
DEDUP_WINDOW = int(os.environ.get("KNOWLEDGE_BUS_DEDUP_HOURS", "24"))


def _encode_body(body: dict) -> str:
    """Serialise `body`, keeping the stored payload VALID JSON when it is oversized.

    The previous `json.dumps(body)[:MAX_BODY_LEN]` sliced the encoded string at a fixed
    byte count, which lands mid-token for any large event — the stored value then failed
    `json.loads` in subscribe(), whose except-clause silently handed consumers a raw
    truncated string instead of a dict. A cross-app bus that corrupts exactly its biggest
    payloads is worse than one that drops them, because the corruption is invisible.
    Oversized bodies now serialise to a well-formed envelope that says so.
    """
    payload = json.dumps(body, default=str)
    if len(payload) <= MAX_BODY_LEN:
        return payload
    marker = {
        "_truncated": True,
        "_original_chars": len(payload),
        "keys": sorted(str(k) for k in body)[:50],
    }
    envelope = json.dumps(marker, default=str)
    if len(envelope) > MAX_BODY_LEN:      # pathological key list — drop the keys too
        envelope = json.dumps({"_truncated": True, "_original_chars": len(payload)})
    return envelope


def _in_filter(values) -> str:
    """Build a PostgREST `in.(...)` filter with each value quoted and escaped.

    Unquoted interpolation broke on any topic containing a comma (it silently split
    into two topics), a parenthesis, or a double quote.
    """
    quoted = []
    for v in values:
        s = str(v).replace("\\", "\\\\").replace('"', '\\"')
        quoted.append(f'"{s}"')
    return f"in.({','.join(quoted)})"


def publish(topic: str, body: dict, project: str = "", source: str = "") -> bool:
    """Publish a knowledge event. Returns True on success."""
    if not topic or not body:
        return False
    try:
        payload = _encode_body(body)
        dedup_key = hashlib.sha256(f"{topic}:{payload}".encode()).hexdigest()[:32]
        # skip if duplicate within window
        existing = db.select("knowledge_events", {
            "select": "id", "dedup_key": f"eq.{dedup_key}",
            "created_at": f"gte.{_hours_ago(DEDUP_WINDOW)}"
        })
        if existing:
            return False
        db.insert("knowledge_events", {
            "topic": topic, "body": payload, "project": project,
            "source": source, "dedup_key": dedup_key
        })
        return True
    except Exception:
        return False


def subscribe(topics: list, since_hours: int = 24, limit: int = 50) -> list:
    """Fetch recent knowledge events for the given topics."""
    if not topics:
        return []
    try:
        params = {
            "select": "topic,body,project,source,created_at",
            "topic": _in_filter(topics),
            "created_at": f"gte.{_hours_ago(since_hours)}",
            "order": "created_at.desc",
            "limit": str(limit),
        }
        rows = db.select("knowledge_events", params) or []
        for r in rows:
            try:
                r["body"] = json.loads(r["body"]) if isinstance(r["body"], str) else r["body"]
            except (json.JSONDecodeError, TypeError):
                pass
        return rows
    except Exception:
        return []


def publish_task_outcome(task: dict, outcome: str, learnings: str = "") -> bool:
    """Convenience: publish a task completion/failure as a knowledge event."""
    return publish(
        topic="task_outcome",
        body={"slug": task.get("slug", ""), "kind": task.get("kind", ""),
              "outcome": outcome, "learnings": learnings},
        project=task.get("project_id", ""),
        source=f"task:{task.get('slug', '')}"
    )


def _hours_ago(h: int) -> str:
    import datetime
    return (datetime.datetime.utcnow() - datetime.timedelta(hours=h)).isoformat()


def run():
    """Print recent knowledge bus events."""
    events = subscribe(["task_outcome", "error_pattern", "fix_pattern"], since_hours=48)
    print(f"knowledge_bus: {len(events)} recent events")
    for e in events[:10]:
        print(f"  [{e.get('topic')}] {e.get('source', '')} @ {e.get('created_at', '')}")
    return events


if __name__ == "__main__":
    run()
