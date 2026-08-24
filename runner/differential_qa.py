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


# Failing-test IDENTIFIERS, which are stable across runs in a way that log text is not.
#   TAP (node --test):  "not ok 12 - name of the test"
#   vitest / jest:      "✕ name", "× name", "FAIL path > name"
#   pytest:             "FAILED path::test_name"
_FAIL_ID = (
    re.compile(r"^\s*not ok\s+\d+\s*-\s*(.+?)\s*$"),
    re.compile(r"^\s*(?:✕|×|✗)\s+(.+?)(?:\s+\d+\s*ms)?\s*$"),
    re.compile(r"^\s*FAILED\s+(.+?)\s*$"),
    re.compile(r"^\s*FAIL\s+(.+?)\s*$"),
)


def test_identifiers(log):
    """The SET of failing-test identifiers in a log, order-independent.

    Why this exists. `node --test` prints its failing-test summary in COMPLETION
    order, which is nondeterministic under concurrency, and merge_train kept only
    the last 6000 characters of output. Running the same tree twice therefore
    produced different tails, different signature lists, and a waiver that was
    granted or refused essentially at random — a whole family of correct branches
    kept landing in TESTFAIL for no reason relating to their content.

    An identifier set has neither problem: it does not care what order the runner
    finished in, and it is derived from the FULL output before any truncation.
    Returned sorted so any downstream cap is deterministic too.
    """
    found = set()
    for raw in _ANSI.sub("", str(log or "")).splitlines():
        line = raw.strip()
        if not line:
            continue
        for pattern in _FAIL_ID:
            m = pattern.match(line)
            if not m:
                continue
            ident = m.group(1).strip()
            ident = _PATH.sub("<path>/", ident)
            ident = _LOC.sub("#", ident)
            ident = _HASH.sub("<sha>", ident)
            ident = re.sub(r"\s+", " ", ident)[:300]
            # "FAIL" with nothing after it, or a bare duration, identifies nothing.
            if len(ident) >= 3 and not ident.isdigit():
                found.add(ident)
            break
    return sorted(found)


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
    # Sorted before the cap. The cap used to keep the first 200 in ENCOUNTER order,
    # so which signatures survived depended on the order the test runner happened to
    # finish in — the same nondeterminism as the truncated tail, one level down.
    return sorted(found)[:200]


def compare(candidate_log, baseline_log, similarity=0.92):
    """Return a waiver only when every candidate failure already exists on prod."""
    if _INFRA.search(str(candidate_log or "")) or _INFRA.search(str(baseline_log or "")):
        return {"allowed": False, "reason": "infrastructure failures are never waived", "new": []}
    # Prefer identifiers when both sides carry them: a set comparison cannot be
    # swayed by the order the runner finished in, or by which failures happened to
    # fall inside a truncated tail. The fuzzy signature path below stays for logs
    # that carry no recognisable test IDs (tsc, lint, build output).
    cand_ids = test_identifiers(candidate_log)
    base_ids = test_identifiers(baseline_log)
    if cand_ids and base_ids:
        new_ids = [i for i in cand_ids if i not in set(base_ids)]
        return {"allowed": not new_ids,
                "reason": "candidate introduces no failing tests beyond the production baseline"
                          if not new_ids
                          else f"candidate introduces {len(new_ids)} new failing test(s)",
                "basis": "test_identifiers",
                "candidate_signatures": len(cand_ids), "baseline_signatures": len(base_ids),
                "new": new_ids[:20]}

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
