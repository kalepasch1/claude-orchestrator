#!/usr/bin/env python3
"""
prompt_bankruptcy.py — Outcome-based prompt bankruptcy (20X-100X savings on losing patterns).

When a prompt pattern repeatedly fails (>N failures on the same template/approach),
declare it "bankrupt" and force a complete rewrite instead of retrying the same losing
prompt. Track prompt lineage and kill losing branches.

The key insight: retrying a failed prompt with the same structure is the #1 source of
wasted tokens. If the first 3 attempts all fail, attempt 4 with the same prompt will
also fail — but costs just as much. Better to restructure the approach entirely.

Mechanics:
  1. Hash the prompt's structural fingerprint (task type + key verbs + target files)
  2. Track outcomes per fingerprint in controls.prompt_lineage
  3. When failures exceed BANKRUPTCY_THRESHOLD, flag the fingerprint as bankrupt
  4. Bankrupt prompts get completely rewritten: different framing, different decomposition,
     or escalation to a human-scoped sub-task

Usage in runner.py:
    import prompt_bankruptcy
    if prompt_bankruptcy.is_bankrupt(task):
        prompt = prompt_bankruptcy.restructure(task, original_prompt)
"""
import os, sys, json, hashlib, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

BANKRUPTCY_THRESHOLD = int(os.environ.get("ORCH_BANKRUPTCY_THRESHOLD", "3"))
BANKRUPTCY_WINDOW_H = float(os.environ.get("ORCH_BANKRUPTCY_WINDOW_H", "48"))  # hours
MAX_LINEAGE = 500  # max tracked fingerprints


def _fingerprint(task):
    """Structural fingerprint of a prompt — ignores variable details, captures intent.

    Two prompts that ask "add field X to model Y" and "add field Z to model W" should
    have DIFFERENT fingerprints (different targets). But retries of the same task should
    have the SAME fingerprint.
    """
    prompt = (task.get("prompt") or "").strip()
    slug = task.get("slug", "")
    project_id = task.get("project_id", "")
    kind = task.get("kind", "")

    # Normalize: lowercase, collapse whitespace, strip numbers/hashes
    norm = re.sub(r"\s+", " ", prompt.lower())
    norm = re.sub(r"[0-9a-f]{8,}", "HASH", norm)  # strip long hex strings
    norm = re.sub(r"\d{4,}", "NUM", norm)  # strip long numbers

    # Include project + kind + first 200 chars of normalized prompt
    raw = f"{project_id}|{kind}|{norm[:200]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _lineage():
    """Load prompt lineage from controls."""
    try:
        rows = db.select("controls", {"select": "value", "key": "eq.prompt_lineage"})
        if rows and rows[0].get("value"):
            v = rows[0]["value"]
            return json.loads(v) if isinstance(v, str) else v
    except Exception:
        pass
    return {}


def _save_lineage(lineage):
    """Save prompt lineage, pruning old entries."""
    # Prune entries older than window
    cutoff = time.time() - BANKRUPTCY_WINDOW_H * 3600
    pruned = {k: v for k, v in lineage.items()
              if v.get("last_attempt", 0) > cutoff}

    # Cap size
    if len(pruned) > MAX_LINEAGE:
        by_time = sorted(pruned.items(), key=lambda x: x[1].get("last_attempt", 0))
        pruned = dict(by_time[-MAX_LINEAGE:])

    try:
        db.upsert("controls", {"key": "prompt_lineage", "value": json.dumps(pruned)})
    except Exception:
        pass


def record_attempt(task, success):
    """Record a task attempt outcome for bankruptcy tracking."""
    fp = _fingerprint(task)
    lineage = _lineage()

    entry = lineage.get(fp, {
        "fingerprint": fp, "slug": task.get("slug", ""),
        "failures": 0, "successes": 0, "total": 0,
        "first_attempt": time.time(), "last_attempt": 0,
        "bankrupt": False, "restructured": False,
    })

    entry["total"] = entry.get("total", 0) + 1
    entry["last_attempt"] = time.time()

    if success:
        entry["successes"] = entry.get("successes", 0) + 1
        # Success clears bankruptcy
        if entry.get("bankrupt"):
            entry["bankrupt"] = False
            entry["restructured"] = False
    else:
        entry["failures"] = entry.get("failures", 0) + 1
        # Check for bankruptcy
        consecutive = entry["failures"] - entry.get("successes", 0)
        if consecutive >= BANKRUPTCY_THRESHOLD:
            entry["bankrupt"] = True

    lineage[fp] = entry
    _save_lineage(lineage)

    return entry


def is_bankrupt(task):
    """Check if a task's prompt pattern is bankrupt (should be restructured)."""
    fp = _fingerprint(task)
    lineage = _lineage()
    entry = lineage.get(fp, {})

    if entry.get("bankrupt"):
        return True

    # Also check: same slug with multiple failures
    failures = entry.get("failures", 0)
    successes = entry.get("successes", 0)
    if failures >= BANKRUPTCY_THRESHOLD and failures > successes * 2:
        return True

    return False


def restructure(task, original_prompt, project=""):
    """Restructure a bankrupt prompt with a completely different approach.

    Strategies:
    1. Decompose: split into smaller sub-tasks
    2. Invert: approach from the test side (write test first, then impl)
    3. Minimize: reduce scope to the smallest possible change
    4. Template: force template adaptation over invention
    """
    fp = _fingerprint(task)
    lineage = _lineage()
    entry = lineage.get(fp, {})
    failures = entry.get("failures", 0)

    # Mark as restructured
    entry["restructured"] = True
    lineage[fp] = entry
    _save_lineage(lineage)

    # Strategy 1: Minimize scope (first restructure attempt)
    if failures <= BANKRUPTCY_THRESHOLD + 1:
        return (
            f"RESTRUCTURED APPROACH (prior attempts failed {failures} times):\n\n"
            f"Make the SMALLEST possible change that satisfies the core requirement. "
            f"Do NOT add tests, do NOT refactor, do NOT improve adjacent code. "
            f"Change exactly ONE thing.\n\n"
            f"ORIGINAL REQUEST:\n{original_prompt[:3000]}"
        )

    # Strategy 2: Test-first inversion
    if failures <= BANKRUPTCY_THRESHOLD + 2:
        return (
            f"RESTRUCTURED APPROACH (prior {failures} attempts all failed):\n\n"
            f"REVERSE your approach: write the TEST first that proves the change works, "
            f"then make the minimum code change to pass that test. If tests already exist, "
            f"identify which one is failing and fix only that.\n\n"
            f"ORIGINAL REQUEST:\n{original_prompt[:3000]}"
        )

    # Strategy 3: Decomposition (escalate)
    return (
        f"RESTRUCTURED APPROACH (BANKRUPT after {failures} failures):\n\n"
        f"This task has failed {failures} times. Do NOT attempt the full change. Instead:\n"
        f"1. Identify the SINGLE smallest file that needs to change\n"
        f"2. Make ONLY that change\n"
        f"3. Ensure the build passes with just that change\n"
        f"4. Report what remains undone so it can be queued as a follow-up task\n\n"
        f"ORIGINAL REQUEST:\n{original_prompt[:2000]}"
    )


def run():
    """Periodic: scan for bankrupt patterns and log stats."""
    lineage = _lineage()
    if not lineage:
        return

    bankrupt = [k for k, v in lineage.items() if v.get("bankrupt")]
    total = len(lineage)
    total_failures = sum(v.get("failures", 0) for v in lineage.values())
    total_successes = sum(v.get("successes", 0) for v in lineage.values())

    if bankrupt:
        print(f"[prompt-bankruptcy] {len(bankrupt)}/{total} patterns bankrupt | "
              f"failures={total_failures} successes={total_successes}")

        # Log to resource_events for dashboard visibility
        try:
            db.insert("resource_events", {
                "kind": "prompt_bankruptcy_scan",
                "detail": json.dumps({
                    "bankrupt": len(bankrupt),
                    "total": total,
                    "failures": total_failures,
                    "successes": total_successes,
                })[:500],
                "action": "scan",
                "created_at": "now()"
            })
        except Exception:
            pass
