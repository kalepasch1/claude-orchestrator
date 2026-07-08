#!/usr/bin/env python3
"""Small typed controls layered on top of the dashboard controls table.

The live controls table started as a pause switch (scope/project/paused), while
some newer jobs also use key/value rows. These helpers tolerate either shape so
feature flags can be explicit without making old deployments brittle.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def _truthy(v):
    return str(v).strip().lower() in ("1", "true", "yes", "on", "enabled")


def get_bool(key, default=False):
    env_key = "ORCH_" + key.upper()
    if env_key in os.environ:
        return _truthy(os.environ.get(env_key))
    try:
        rows = db.select("controls", {"select": "key,value", "key": f"eq.{key}",
                                      "order": "updated_at.desc", "limit": "1"}) or []
        if rows:
            raw = rows[0].get("value")
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    pass
            if isinstance(raw, dict):
                raw = raw.get("enabled", raw.get("value"))
            return _truthy(raw)
    except Exception:
        pass
    try:
        rows = db.select("controls", {"select": "scope,project,paused,reason", "scope": "eq.config",
                                      "project": f"eq.{key}", "order": "updated_at.desc",
                                      "limit": "1"}) or []
        if rows:
            reason = rows[0].get("reason") or ""
            if "enabled" in reason.lower() or "true" in reason.lower():
                return True
            if "disabled" in reason.lower() or "false" in reason.lower():
                return False
            return not bool(rows[0].get("paused"))
    except Exception:
        pass
    return bool(default)


def use_purchased_credits(default=False):
    return get_bool("use_purchased_credits", default)


def ensure_use_purchased_credits_row(enabled=False):
    """Best-effort dashboard row. Works on either controls schema."""
    value = {"enabled": bool(enabled), "purpose": "Allow paid API credits when value beats subscription/local routes"}
    try:
        db.insert("controls", {"key": "use_purchased_credits", "value": json.dumps(value),
                               "updated_at": "now()"}, upsert=True)
        return True
    except Exception:
        pass
    try:
        db.insert("controls", {"scope": "config", "project": "use_purchased_credits",
                               "paused": not bool(enabled),
                               "reason": "enabled" if enabled else "disabled",
                               "updated_by": "orchestrator", "updated_at": "now()"},
                  upsert=True)
        return True
    except Exception:
        return False
