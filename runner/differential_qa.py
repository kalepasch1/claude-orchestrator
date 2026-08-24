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
_SIGNATURE_CAP = 200
# Failing-test identifiers, per runner. TAP: "not ok 3 - name". vitest/jest:
# "× name" / "✕ name" / "FAIL name". pytest: "FAILED path::test".
_TAP_FAIL = re.compile(r"^not ok\s+\d+\s*[-–]?\s*(?P<name>.+)$", re.I)
_VITEST_FAIL = re.compile(r"^(?:[×✕✖x]|FAIL)\s+(?P<name>\S.*)$")
_PYTEST_FAIL = re.compile(r"^FAILED\s+(?P<name>\S+::\S+)")


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
    # Sort BEFORE capping. Capping in encounter order made which signatures
    # survived depend on runner ordering, so two runs of the same failing suite
    # could yield different comparable sets and a regression could be waived
    # purely because it was reported late. Sorting makes the cap deterministic.
    return sorted(found)[:_SIGNATURE_CAP]


def test_identifiers(log):
    """Failing-test IDs parsed from the FULL output, deduplicated and sorted.

    Signature matching reads log LINES, so it is at the mercy of whatever the
    truncated tail happens to contain. Test identifiers are the stable thing a
    runner emits per failure, so when both sides carry them they give an exact
    comparison instead of a fuzzy one. Returns [] for logs with no test IDs
    (tsc/lint/build), which keeps those comparable through `signatures()`.
    """
    found = set()
    for raw in _ANSI.sub("", str(log or "")).splitlines():
        line = raw.strip()
        if not line:
            continue
        for pattern in (_TAP_FAIL, _VITEST_FAIL, _PYTEST_FAIL):
            match = pattern.match(line)
            if match:
                name = re.sub(r"\s+", " ", match.group("name").strip())
                # Drop the trailing duration vitest/jest append: "name 12ms".
                name = re.sub(r"\s+\d+(?:\.\d+)?\s*m?s$", "", name)
                if name:
                    found.add(name[:500])
                break
    return sorted(found)


def compare(candidate_log, baseline_log, similarity=0.92):
    """Return a waiver only when every candidate failure already exists on prod."""
    if _INFRA.search(str(candidate_log or "")) or _INFRA.search(str(baseline_log or "")):
        return {"allowed": False, "reason": "infrastructure failures are never waived", "new": []}
    # Prefer identifier sets when BOTH sides carry them: they come from the full
    # output rather than a truncated tail, so the comparison is exact instead of
    # fuzzy. Logs with no test IDs (tsc/lint/build) fall through to signatures,
    # which must stay comparable for those commands.
    candidate_ids = test_identifiers(candidate_log)
    baseline_ids = test_identifiers(baseline_log)
    if candidate_ids and baseline_ids:
        new_ids = [item for item in candidate_ids if item not in set(baseline_ids)]
        return {"allowed": not new_ids,
                "reason": "candidate fails no test the production baseline passes"
                          if not new_ids
                          else f"candidate introduces {len(new_ids)} new failing test(s)",
                "basis": "test_identifiers",
                "candidate_tests": len(candidate_ids), "baseline_tests": len(baseline_ids),
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
