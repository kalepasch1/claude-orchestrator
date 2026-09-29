#!/usr/bin/env python3
"""consilium_controls.py — write Consilium heartbeat/stat rows to `controls` so they actually land.

2026-09-28: `db.upsert("controls", {"key": ..., "value": ...})` returned None and wrote nothing —
`controls.scope` is required, the insert was rejected, and the rejection was swallowed. The
heartbeat and theory-lab stats had therefore never been written once. Rows are keyed by
(scope='consilium', key); select-then-update avoids depending on a conflict target.
"""
from __future__ import annotations
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

SCOPE = "consilium"


def put(key, value):
    """Store a JSON-serialisable value. Returns True when the row was confirmed written."""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    try:
        rows = db.select("controls", {"select": "id", "key": f"eq.{key}", "scope": f"eq.{SCOPE}", "limit": "1"}) or []
        if rows:
            out = db.update("controls", {"id": rows[0]["id"]},
                            {"value": text, "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                             "updated_by": "consilium"})
        else:
            out = db.insert("controls", {"key": key, "scope": SCOPE, "value": text, "updated_by": "consilium"})
        return bool(out)
    except Exception:
        return False


def get(key, default=None):
    try:
        rows = db.select("controls", {"select": "value", "key": f"eq.{key}", "scope": f"eq.{SCOPE}", "limit": "1"}) or []
        if rows and rows[0].get("value"):
            v = rows[0]["value"]
            return json.loads(v) if isinstance(v, str) else v
    except Exception:
        pass
    return default
