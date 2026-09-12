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
_SIGNATURE_CAP = 200
_CACHE_SCHEMA = "v2-equal-qa-evidence"
_CACHE_LOG_CHARS = 24000

# Patterns for extracting structured test identifiers from runner output.
# TAP: "not ok 3 - my test name"
_TAP_FAIL = re.compile(r"^not ok\s+\d+\s*[-–]\s*(.+)", re.M)
# vitest / jest: "  ✕ my test name" or "  × my test name" or "  ✖ my test name" or "FAIL src/foo.test.ts"
_VITEST_FAIL = re.compile(r"^\s*[✕×✖]\s+(.+?)(?:\s+\(\d+\s*m?s\))?\s*$", re.M)
_JEST_FAIL_FILE = re.compile(r"^FAIL\s+(.+?)(?:\s+\(\d+\s*m?s\))?\s*$", re.M)
# pytest: "FAILED path/to/test.py::test_name"
_PYTEST_FAIL = re.compile(r"^FAILED\s+(\S+::\S+)", re.M)
# node:test "✖ name" at start of line
_NODE_FAIL = re.compile(r"^✖\s+(.+?)(?:\s+\(\d+\s*m?s\))?\s*$", re.M)


def test_identifiers(log):
    """Parse failing-test IDs from the FULL output into a deduplicated sorted set.

    Returns a sorted list of unique test-failure identifiers extracted from TAP,
    vitest/jest, pytest, and node:test output formats. Empty list if no
    structured test IDs are found (e.g. tsc/lint/build output).
    """
    text = _ANSI.sub("", str(log or ""))
    ids = set()
    for pat in (_TAP_FAIL, _VITEST_FAIL, _JEST_FAIL_FILE, _PYTEST_FAIL, _NODE_FAIL):
        for m in pat.finditer(text):
            ident = m.group(1).strip()
            if ident:
                ids.add(ident)
    return sorted(ids)


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
    # Sort before capping so the surviving set is deterministic regardless of
    # runner ordering — the original encounter-order cap made the waiver
    # decision nondeterministic under concurrent test execution.
    found.sort()
    return found[:_SIGNATURE_CAP]


def _compare_by_identifiers(candidate_ids, baseline_ids):
    """Set-based comparison: every candidate failure must appear in the baseline."""
    new = sorted(set(candidate_ids) - set(baseline_ids))
    return {"allowed": not new,
            "basis": "test_identifiers",
            "reason": "candidate introduces no failures beyond production baseline" if not new
                      else f"candidate introduces {len(new)} new failing test(s)",
            "candidate_identifiers": len(candidate_ids),
            "baseline_identifiers": len(baseline_ids),
            "new": new[:20]}


def compare(candidate_log, baseline_log, similarity=0.92):
    """Return a waiver only when every candidate failure already exists on prod."""
    if _INFRA.search(str(candidate_log or "")) or _INFRA.search(str(baseline_log or "")):
        return {"allowed": False, "reason": "infrastructure failures are never waived", "new": []}
    # Prefer structured test identifiers when both sides carry them — they are
    # order-independent and truncation-safe by construction.
    cand_ids = test_identifiers(candidate_log)
    base_ids = test_identifiers(baseline_log)
    if cand_ids and base_ids:
        return _compare_by_identifiers(cand_ids, base_ids)
    # Fall back to the existing fuzzy signature match for logs with no
    # structured test IDs (tsc, lint, build output).
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
            "basis": "fuzzy_signatures",
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
