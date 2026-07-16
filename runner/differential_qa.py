#!/usr/bin/env python3
"""Baseline-aware QA: block candidate regressions, not unchanged production debt."""
import difflib
import hashlib
import json
import os
import re
import time


_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_PATH = re.compile(r"(?:/[^\s:]+)+/")
_LOC = re.compile(r"(?<=[:(])\d+(?=[:),])")
_HASH = re.compile(r"\b[0-9a-f]{12,40}\b", re.I)
_SIGNAL = re.compile(r"error|fail|assert|TS\d{4}|✖|×|not assignable|cannot find", re.I)
_INFRA = re.compile(r"timed out|timeout|ENOMEM|out of memory|killed|cannot find module|module not found|command not found|dependency prewarm", re.I)
_CACHE_SCHEMA = "v2-equal-qa-evidence"
_CACHE_LOG_CHARS = 24000


def signatures(log):
    found = []
    for raw in _ANSI.sub("", str(log or "")).splitlines():
        line = raw.strip()
        if not line or not _SIGNAL.search(line):
            continue
        line = _PATH.sub("<path>/", line)
        line = _LOC.sub("#", line)
        line = _HASH.sub("<sha>", line)
        line = re.sub(r"\s+", " ", line)[:500]
        if line not in found:
            found.append(line)
    return found[:200]


def compare(candidate_log, baseline_log, similarity=0.92):
    """Return a waiver only when every candidate failure already exists on prod."""
    if _INFRA.search(str(candidate_log or "")) or _INFRA.search(str(baseline_log or "")):
        return {"allowed": False, "reason": "infrastructure failures are never waived", "new": []}
    candidate = signatures(candidate_log)
    baseline = signatures(baseline_log)
    if not candidate or not baseline:
        return {"allowed": False, "reason": "insufficient comparable failure evidence", "new": candidate}
    if not any(len(item) >= 25 for item in candidate):
        return {"allowed": False, "reason": "failure evidence is too generic to waive", "new": candidate}
    new = []
    for item in candidate:
        if not any(item == old or difflib.SequenceMatcher(None, item, old).ratio() >= similarity
                   for old in baseline):
            new.append(item)
    return {"allowed": not new,
            "reason": "candidate introduces no failures beyond production baseline" if not new
                      else f"candidate introduces {len(new)} new failure signature(s)",
            "candidate_signatures": len(candidate), "baseline_signatures": len(baseline),
            "new": new[:20]}


def _cache_path():
    home = os.environ.get("CLAUDE_ORCH_HOME", os.path.join(os.path.dirname(__file__), "..", ".runtime"))
    os.makedirs(home, exist_ok=True)
    return os.path.join(home, "differential-qa-cache.json")


def cache_key(repo, ref, command):
    raw = f"{_CACHE_SCHEMA}\0{os.path.realpath(repo)}\0{ref}\0{command}"
    return hashlib.sha256(raw.encode()).hexdigest()


def cached(repo, ref, command, ttl_s=86400):
    try:
        data = json.load(open(_cache_path(), encoding="utf-8"))
        row = data.get(cache_key(repo, ref, command))
        return row if row and time.time() - float(row.get("at", 0)) <= ttl_s else None
    except Exception:
        return None


def store(repo, ref, command, ok, log):
    try:
        path = _cache_path()
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            data = {}
        data[cache_key(repo, ref, command)] = {
            "at": time.time(), "ok": bool(ok), "log": str(log or "")[-_CACHE_LOG_CHARS:]}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as target:
            json.dump(data, target)
        os.replace(tmp, path)
    except Exception:
        pass
