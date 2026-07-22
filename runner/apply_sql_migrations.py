#!/usr/bin/env python3
"""Apply selected idempotent SQL migrations through the Supabase Management API."""
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # loads runner/.env


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULTS = [
    "supabase/migrations/0028_controls_key_value_flags.sql",
    "supabase/migrations/0029_orchestrator_routing_telemetry.sql",
    "supabase/migrations/0030_reuse_and_verifier_intelligence.sql",
]


def _split(sql):
    parts, cur, quote, dollar = [], [], None, None
    i = 0
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i:i + 2]
        if dollar:
            if sql.startswith(dollar, i):
                cur.append(dollar)
                i += len(dollar)
                dollar = None
                continue
            cur.append(ch)
            i += 1
            continue
        if quote is None and nxt == "--":
            j = sql.find("\n", i)
            if j == -1:
                break
            i = j + 1
            continue
        if quote is None and ch == "$":
            m = re.match(r"\$[A-Za-z_0-9]*\$", sql[i:])
            if m:
                dollar = m.group(0)
                cur.append(dollar)
                i += len(dollar)
                continue
        if ch in ("'", '"'):
            if quote == ch:
                quote = None
            elif quote is None:
                quote = ch
        if ch == ";" and quote is None:
            stmt = "".join(cur).strip()
            if stmt:
                parts.append(stmt)
            cur = []
        else:
            cur.append(ch)
        i += 1
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


def _query(ref, token, sql):
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{ref}/database/query",
        data=json.dumps({"query": sql}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST")
    raw = urllib.request.urlopen(req, timeout=60).read().decode()
    return json.loads(raw) if raw else None


def apply(paths):
    token = os.environ.get("SUPABASE_ACCESS_TOKEN")
    ref = os.environ.get("SUPABASE_PROJECT_REF")
    if not token or not ref:
        raise SystemExit("SUPABASE_ACCESS_TOKEN and SUPABASE_PROJECT_REF are required")
    applied = []
    for rel in paths:
        path = rel if os.path.isabs(rel) else os.path.join(ROOT, rel)
        sql = open(path).read()
        for stmt in _split(sql):
            _query(ref, token, stmt)
        applied.append(rel)
    return applied


if __name__ == "__main__":
    paths = sys.argv[1:] or DEFAULTS
    print(json.dumps({"applied": apply(paths)}, indent=2))
