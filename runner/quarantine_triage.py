#!/usr/bin/env python3
"""
quarantine_triage.py — 3-tier quarantine triage for automatic recovery.

Tier 1 — Flake detection (catches ~60% of transients):
    Hash test output; if a task fails with the same hash as a known flake,
    retry immediately with 2^n backoff. Flakes are identified by seeing
    different output hashes across retries of the same test.

Tier 2 — Infra failures (network, disk, runner OOM):
    Detect infra-class errors via pattern matching. Trigger runner restart
    recommendation + 1 automatic retry.

Tier 3 — Code/config failures:
    Genuine bugs. Escalate to ops with a root-cause summary extracted from
    the failure output.

Called by blocker_quarantine.py before parking a task, giving it a chance to
self-recover without human intervention.
"""
import hashlib
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MAX_FLAKE_RETRIES = int(os.environ.get("ORCH_FLAKE_RETRY_MAX", "3"))
INFRA_RETRY_MAX = int(os.environ.get("ORCH_INFRA_RETRY_MAX", "1"))


# ── Tier 1: Flake detection ──────────────────────────────────────────────────

# Known flake output patterns (timing-sensitive, order-dependent, resource contention)
_FLAKE_HINTS = re.compile(
    r"ECONNRESET|ETIMEDOUT|ECONNREFUSED|ENOSPC|"
    r"socket hang up|connection reset|"
    r"resource temporarily unavailable|"
    r"too many open files|"
    r"lock timeout|deadlock|"
    r"flaky|intermittent|transient",
    re.I,
)

def _output_hash(output):
    """Normalize and hash test output for flake comparison."""
    cleaned = re.sub(r'\d+\.\d+s', 'Xs', output or "")
    cleaned = re.sub(r'at \d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}', 'at DATE', cleaned)
    cleaned = re.sub(r'pid \d+', 'pid N', cleaned)
    cleaned = re.sub(r'port \d+', 'port N', cleaned)
    return hashlib.sha256(cleaned.encode(errors="replace")).hexdigest()[:16]


def _get_prior_hashes(task_id):
    """Retrieve prior failure hashes for this task from fleet_config."""
    try:
        rows = db.select("fleet_config", {
            "select": "value",
            "key": f"eq.quarantine_hashes:{task_id}",
        }) or []
        if rows:
            return rows[0].get("value", "").split(",")
    except Exception:
        pass
    return []


def _record_hash(task_id, h):
    """Append a failure hash to this task's history."""
    try:
        prior = _get_prior_hashes(task_id)
        prior.append(h)
        # Keep last 10
        db.insert("fleet_config", {
            "key": f"quarantine_hashes:{task_id}",
            "value": ",".join(prior[-10:]),
        }, on_conflict="key", merge_patch={"value": "EXCLUDED.value"})
    except Exception:
        pass


def is_flake(task_id, output):
    """Tier 1: Check if this failure is a flake (different hash from prior runs)."""
    h = _output_hash(output)
    prior = _get_prior_hashes(task_id)
    _record_hash(task_id, h)

    if not prior:
        return False, h  # First failure, can't tell yet

    # If we see a DIFFERENT hash than prior failures, it's likely a flake
    if any(ph != h for ph in prior[-3:]):
        return True, h

    # If output matches known flake patterns
    if _FLAKE_HINTS.search(output or ""):
        return True, h

    return False, h


# ── Tier 2: Infra failure detection ──────────────────────────────────────────

_INFRA_PATTERNS = re.compile(
    r"out of memory|OOM|oom-kill|"
    r"no space left on device|ENOSPC|disk full|"
    r"network (?:error|unreachable|timeout)|"
    r"DNS resolution failed|"
    r"cannot allocate memory|"
    r"worker process exited|"
    r"runner crash|runner died|"
    r"git fetch.*fatal|"
    r"worktree.*locked|"
    r"cannot create worktree|"
    r"permission denied.*\.git|"
    r"fatal: unable to access",
    re.I,
)


def is_infra_failure(output):
    """Tier 2: Detect infrastructure-class failures."""
    if not output:
        return False, ""
    m = _INFRA_PATTERNS.search(output)
    if m:
        return True, m.group(0)[:100]
    return False, ""


# ── Tier 3: Code/config failure (escalation) ─────────────────────────────────

_CODE_PATTERNS = [
    (re.compile(r"TypeError|ReferenceError|SyntaxError", re.I), "js-runtime-error"),
    (re.compile(r"ImportError|ModuleNotFoundError|NameError", re.I), "python-import-error"),
    (re.compile(r"type error|cannot find module", re.I), "typescript-error"),
    (re.compile(r"build fail|compilation error", re.I), "build-error"),
    (re.compile(r"test fail|assertion|expect.*to", re.I), "test-failure"),
    (re.compile(r"merge conflict|CONFLICT", re.I), "merge-conflict"),
    (re.compile(r"missing.*config|env.*not set|undefined.*variable", re.I), "config-error"),
]


def classify_code_failure(output):
    """Tier 3: Classify the root cause of a code/config failure."""
    if not output:
        return "unknown", ""

    for pattern, category in _CODE_PATTERNS:
        m = pattern.search(output)
        if m:
            # Extract a short root-cause summary (the matching line + context)
            start = max(0, m.start() - 100)
            end = min(len(output), m.end() + 200)
            summary = output[start:end].strip()
            return category, summary[:300]

    return "unknown", output[-300:] if len(output) > 300 else output


# ── Main triage entry point ──────────────────────────────────────────────────

def triage(task, output):
    """Run 3-tier triage on a failing task.

    Returns:
        dict with keys:
            tier (int): 1=flake, 2=infra, 3=code
            action (str): "retry", "restart+retry", "escalate"
            category (str): failure classification
            summary (str): root-cause summary for ops
            backoff_s (int): seconds to wait before retry (tier 1/2)
            retry_count (int): how many retries have been attempted
    """
    task_id = task.get("id", "")
    note = task.get("note") or ""
    rc = int(task.get("remediation_count") or 0)

    result = {
        "tier": 3,
        "action": "escalate",
        "category": "unknown",
        "summary": "",
        "backoff_s": 0,
        "retry_count": rc,
    }

    # Tier 1: Flake detection
    flake, h = is_flake(task_id, output)
    if flake and rc < MAX_FLAKE_RETRIES:
        result["tier"] = 1
        result["action"] = "retry"
        result["category"] = "flake"
        result["summary"] = f"flake detected (hash={h}), retry {rc+1}/{MAX_FLAKE_RETRIES}"
        result["backoff_s"] = 2 ** rc  # exponential backoff
        return result

    # Tier 2: Infra failure
    infra, infra_detail = is_infra_failure(output)
    if infra and rc < (MAX_FLAKE_RETRIES + INFRA_RETRY_MAX):
        result["tier"] = 2
        result["action"] = "restart+retry"
        result["category"] = "infra"
        result["summary"] = f"infra failure: {infra_detail}"
        result["backoff_s"] = 30  # wait for runner restart
        return result

    # Tier 3: Code/config failure — escalate with root-cause
    category, summary = classify_code_failure(output)
    result["tier"] = 3
    result["action"] = "escalate"
    result["category"] = category
    result["summary"] = summary
    return result
