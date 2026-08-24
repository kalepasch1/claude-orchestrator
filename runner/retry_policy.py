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
    # provider credit/spend exhaustion (e.g. xai 403 permission-denied "used all
    # available credits / monthly spending limit") — recoverable via provider
    # rotation or the monthly reset, same class as "budget cap" (canary-codex-4)
    r"spending limit|available credits|out of credits|insufficient credits|quota exceeded|"
    r"name resolution|dns|ssl|handshake|reset by peer|"
    r"409|conflict|duplicate key|already exists)",
    re.I,
)

# Provider credit / spend exhaustion, specifically.
#
# These are a SUBSET of _TRANSIENT and stay there: the work is still retryable, because
# another provider or the monthly reset can serve it. What they are NOT is a defect in the
# task's code, and telling the two apart matters at exactly one place — the agentic repair
# chokepoint, which otherwise rewrites the task's prompt into engineering instructions.
#
# That rewrite is not hypothetical. It produced a queued task whose entire body read:
#
#   "The task failed due to an API error indicating that the team has either used all
#    available credits or reached its monthly spending limit. ... Modify the relevant
#    configuration or source code to use a different API key, increase the spending limit,
#    or purchase additional credits if necessary."
#
# No coding agent can buy credits, and none should try. Kept as one named pattern here
# rather than a second copy next to the consumer, because a duplicated table of phrases is
# a table that drifts.
_PROVIDER_QUOTA = re.compile(
    r"(spending limit|available credits|out of credits|insufficient credits|"
    r"quota exceeded|credit balance|billing|payment required|402)",
    re.I,
)


def is_provider_quota(note: str) -> bool:
    """True when a failure is the provider refusing on credit/spend, not the work failing.

    Never raises: an unreadable note is simply not a quota signal, and a guess in either
    direction is worse than deferring to the caller's existing behaviour.
    """
    try:
        return bool(note and _PROVIDER_QUOTA.search(str(note)))
    except Exception:                                    # noqa: BLE001
        return False


# Terminal (do NOT auto-retry) signatures — genuine work failures / gated decisions.
_TERMINAL = re.compile(
    r"(agent run failed|no committable|changed nothing|no file changes|"
    r"verify:|quality gate|judge:|legal review|awaiting.*approval|"
    r"exhausted retries|two-key)",
    re.I,
)


def classify(note: str) -> str:
    """Return 'transient' or 'terminal' for a BLOCKED/exception note.

    Checks the adaptive outcome tracker first; falls back to static regexes
    so that novel error messages improve classification over time rather than
    always defaulting to 'terminal' until someone adds a new regex.
    """
    n = note or ""
    # terminal signatures always win — judge/verify/legal are never transient
    if _TERMINAL.search(n):
        return "terminal"
    # A provider refusing on credit is always retryable, and it must be checked HERE rather
    # than left to _TRANSIENT's phrase list. That list carried "available credits" and
    # "insufficient credits" but not "credit balance", which is the wording Anthropic
    # actually returns — so `Your credit balance is too low` matched nothing, fell through
    # to the terminal default, and permanently blocked the task over a billing blip. One
    # predicate, consulted before the fallthrough, closes the whole family.
    if is_provider_quota(n):
        return "transient"
    # adaptive layer: learned outcome history overrides the default before regex
    try:
        import error_outcome_tracker
        suggestion = error_outcome_tracker.suggest(n)
        if suggestion:
            return suggestion
    except Exception:
        pass
    if _TRANSIENT.search(n):
        return "transient"
    return "terminal"  # unknown -> treat as terminal (safer; a human sees it)


def record_outcome(note: str, succeeded: bool) -> None:
    """Record whether a task that was classified from this error note succeeded.

    Call this after a retried task resolves (merged or permanently failed) so
    the adaptive layer can improve future classification of similar errors.
    Fail-soft: any exception is silently swallowed.
    """
    try:
        import error_outcome_tracker
        was_transient = classify(note) == "transient"
        error_outcome_tracker.record(note, was_transient, succeeded)
    except Exception:
        pass


def backoff_seconds(transient_retries: int) -> float:
    """Exponential backoff with +/-25% jitter, capped at BACKOFF_CAP_S.

    Formula: min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2^n) * uniform(0.75, 1.25).
    With defaults (base=5s, cap=120s): retry 0 → ~5s, retry 4 → ~80s, retry 5+ → ~120s.
    """
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
