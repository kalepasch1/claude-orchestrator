#!/usr/bin/env python3
"""
retry_policy.py - the reliability fix that stops a handful of TRANSIENT failures from freezing
whole dependency trees.

Real incident this fixes: `tomorrow` had 115 QUEUED tasks with 0 claimable because a few
FOUNDATION tasks went BLOCKED on transient causes ("budget cap reached", "Connection reset by
peer"). Every descendant then had an unsatisfied dep, so the entire project stalled and required
a MANUAL requeue. Transient failures must never be terminal.

Policy:
  * classify(note) -> "transient" | "terminal"
      transient = network blips, rate limits, provider overload/5xx, timeouts, and NOTIONAL
      "budget cap reached" (which in subscription mode is free $0 work being throttled).
      terminal  = the agent genuinely failed the work (tests failed, no changes, judge/verify
      rejected, legal gate) — those SHOULD stay BLOCKED for a human/re-scope.
  * decide(note, transient_retries) -> {"action","backoff_s","note"}
      transient & under cap -> REQUEUE with exponential backoff (caps a runaway retry loop).
      otherwise             -> BLOCK (terminal).

Used by:
  * runner._run_task_safe  (auto-recover a transient exception instead of terminal BLOCKED)
  * periodic sweep         (safety net: requeue any transient-BLOCKED task under the cap)
"""
import os, re

# max automatic transient retries before we give up and leave it BLOCKED for a human
MAX_TRANSIENT_RETRIES = int(os.environ.get("MAX_TRANSIENT_RETRIES", "50"))
# base backoff seconds; actual = min(BACKOFF_CAP, BASE * 2**n) with light jitter
BACKOFF_BASE_S = float(os.environ.get("RETRY_BACKOFF_BASE_S", "5"))
BACKOFF_CAP_S = float(os.environ.get("RETRY_BACKOFF_CAP_S", "120"))

# Transient (recoverable) signatures — safe to auto-retry.
_TRANSIENT = re.compile(
    r"(connection reset|urlopen|errno|timed?\s?out|timeout|temporar|"
    r"rate.?limit|overload|429|500|502|503|504|"
    r"service unavailable|read timed out|broken pipe|"
    r"budget cap|cost circuit|http error 409|409: conflict|postgrest|high demand|try again|econnreset|"
    r"name resolution|dns|ssl|handshake|reset by peer|"
    r"409|conflict|duplicate key|already exists)",
    re.I,
)

# Terminal (do NOT auto-retry) signatures — genuine work failures / gated decisions.
_TERMINAL = re.compile(
    r"(agent run failed|no committable|changed nothing|no file changes|"
    r"verify:|quality gate|judge:|legal review|awaiting.*approval|"
    r"exhausted retries|two-key)",
    re.I,
)


def classify(note: str) -> str:
    """Return 'transient' or 'terminal' for a BLOCKED/exception note."""
    n = note or ""
    # terminal signatures win: a judge/verify/legal decision is never "transient"
    if _TERMINAL.search(n):
        return "terminal"
    if _TRANSIENT.search(n):
        return "transient"
    return "terminal"  # unknown -> treat as terminal (safer; a human sees it)


def backoff_seconds(transient_retries: int) -> float:
    import random
    n = max(0, int(transient_retries or 0))
    base = min(BACKOFF_CAP_S, BACKOFF_BASE_S * (2 ** n))
    return round(base * (0.75 + 0.5 * random.random()), 1)  # +/-25% jitter


def decide(note: str, transient_retries: int = 0) -> dict:
    """
    Decide what to do with a failing task.
    Returns {"action": "requeue"|"block", "backoff_s": float, "transient_retries": int, "note": str}.
    """
    kind = classify(note)
    tr = int(transient_retries or 0)
    if kind == "transient" and tr < MAX_TRANSIENT_RETRIES:
        return {"action": "requeue", "backoff_s": backoff_seconds(tr),
                "transient_retries": tr + 1,
                "note": f"transient ({tr + 1}/{MAX_TRANSIENT_RETRIES}); agentic-repair assignment: {(note or '')[:120]}"}
    if kind == "transient":
        return {"action": "requeue", "backoff_s": BACKOFF_CAP_S, "transient_retries": tr + 1,
                "note": f"transient cap reached; still auto-requeued for cooldown/failover: {(note or '')[:120]}"}
    return {"action": "block", "backoff_s": 0, "transient_retries": tr, "note": note}


if __name__ == "__main__":
    tests = [
        ("runner exception: <urlopen error [Errno 54] Connection reset by peer>", 0),
        ("budget cap reached", 2),
        ("agent run failed", 0),
        ("judge: diff introduces SQL injection", 0),
        ("legal review required: money transmission", 0),
        ("high demand, try again", 4),
        ("high demand, try again", 5),
        ("some totally novel error", 0),
    ]
    for note, tr in tests:
        print(f"tr={tr:2d} {classify(note):9s} -> {decide(note, tr)['action']:7s}  | {note[:50]}")
