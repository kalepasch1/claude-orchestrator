#!/usr/bin/env python3
"""Compile repeated release failures into stable, signature-specific repair work."""
import hashlib
import json
import os
import re
import time


def normalize(text):
    value = str(text or "").lower()
    value = re.sub(r"/[^\s:]+", "<path>", value)
    value = re.sub(r"\b[0-9a-f]{7,64}\b", "<hash>", value)
    value = re.sub(r"\b\d+\b", "<n>", value)
    return re.sub(r"\s+", " ", value).strip()[-1200:]


def signature(kind, text):
    return hashlib.sha256(f"{kind}:{normalize(text)}".encode()).hexdigest()[:12]


def task_slug(prefix, project, kind, text):
    return f"{prefix}-{project}-{signature(kind, text)}"


def record(project, kind, text):
    home = os.environ.get("CLAUDE_ORCH_HOME", os.path.join(os.path.dirname(__file__), "..", ".runtime"))
    path = os.path.join(home, "failure-playbooks.json")
    try:
        data = json.load(open(path)) if os.path.exists(path) else {}
    except Exception:
        data = {}
    sig = signature(kind, text)
    row = data.get(sig) or {"project": project, "kind": kind, "count": 0,
                            "normalized": normalize(text)[:500]}
    row["count"] = int(row.get("count") or 0) + 1
    row["last_seen"] = time.time()
    data[sig] = row
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
    except OSError:
        pass
    return {"signature": sig, **row}
