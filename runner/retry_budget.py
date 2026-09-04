#!/usr/bin/env python3
"""
retry_budget.py - adaptive retry budgets.

Instead of blindly retrying every task 4 times, this module uses historical
outcome data to decide how many retries a task deserves.  It classifies errors,
checks whether retries have historically helped for a given slug prefix, and
caps attempts for trivial/simple tasks that rarely benefit from deep retries.

Env knobs:
    ORCH_RETRY_BUDGET_ENABLED     "true" (default) / "false"
    ORCH_RETRY_DEFAULT_MAX        default max attempts when no data (default "4")
"""
import sys, os, json, time, threading, hashlib
from typing import Optional
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("retry_budget")
import db

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ENABLED     = os.environ.get("ORCH_RETRY_BUDGET_ENABLED", "true").lower() == "true"
DEFAULT_MAX = int(os.environ.get("ORCH_RETRY_DEFAULT_MAX", "4"))
TTL         = 300  # cache TTL in seconds

# Error classification keywords
_RATE_LIMIT_PATTERNS   = ("rate_limit", "rate limit", "429", "too many requests", "quota", "overloaded")
_TIMEOUT_PATTERNS      = ("timeout", "timed out", "deadline exceeded", "context deadline")
_ASSERTION_PATTERNS    = ("assert", "assertion", "expected", "test fail", "tests_passed.*false")

# Provider-level exhaustion: the provider refused before the coder ever ran, so the
# attempt produced no work to learn from.  Matches retry_policy.classify()=="transient"
# for the same strings (see tests/test_retry_policy_spend_limit.py) — the xai 403
# "used all available credits / monthly spending limit" family.  These are checked
# BEFORE _RATE_LIMIT_PATTERNS because "quota exceeded" would otherwise be swallowed
# by the rate-limit bucket and charged to the budget.
_PROVIDER_EXHAUSTED_PATTERNS = (
    "used all available credits",
    "monthly spending limit",
    "spending limit",
    "out of credits",
    "insufficient credits",
    "insufficient_quota",
    "quota exceeded",
    "permission-denied",
    "permission_denied",
    "billing",
    "payment required",
    "402",
)

# Complexity tiers that cap retries
_LOW_COMPLEXITY = ("trivial", "simple")
_HIGH_COMPLEXITY = ("complex", "very_complex")


def _slug_prefix(slug):
    """First two hyphen-delimited segments: 'add-field-users-email' -> 'add-field'."""
    parts = (slug or "").split("-")
    return "-".join(parts[:2]) if len(parts) >= 2 else (slug or "unknown")


def _classify_error(error_str):
    """Classify an error string into a category."""
    if not error_str:
        return "unknown"
    low = error_str.lower()
    if any(p in low for p in _PROVIDER_EXHAUSTED_PATTERNS):
        return "provider_exhausted"
    if any(p in low for p in _RATE_LIMIT_PATTERNS):
        return "rate_limit"
    if any(p in low for p in _TIMEOUT_PATTERNS):
        return "timeout"
    if any(p in low for p in _ASSERTION_PATTERNS):
        return "assertion"
    return "other"


def _get_complexity(task):
    """Extract estimated_complexity from task's preopt ai_review data."""
    try:
        # Try preopt cache first
        preopt = task.get("_preopt") or {}
        ai = preopt.get("ai_review") or {}
        c = ai.get("estimated_complexity")
        if c:
            return c
        # Try direct queue_preopt lookup
        import queue_preopt
        cached = queue_preopt.get(task.get("id"))
        if cached:
            ai2 = (cached.get("ai_review") or {})
            return ai2.get("estimated_complexity", "")
    except Exception:
        pass
    return ""


def _rotation_target(task):
    """Suggest a provider to rotate to when the current one is credit-exhausted.

    Returns a model string, or None when no distinct alternative is configured.
    ORCH_PROVIDER_ROTATION is a comma-separated preference list; the first entry
    that does not share a provider prefix with the task's current coder wins.
    Fail-soft: any error yields None, and the caller keeps its own routing.
    """
    try:
        chain = [m.strip() for m in os.environ.get(
            "ORCH_PROVIDER_ROTATION",
            "claude:claude-haiku-4-5-20251001,google:gemini-2.0-flash,local:qwen2.5-coder:32b",
        ).split(",") if m.strip()]
        current = (task.get("force_coder") or task.get("model") or "")
        cur_provider = current.split(":", 1)[0].lower()
        for candidate in chain:
            if candidate.split(":", 1)[0].lower() != cur_provider:
                return candidate
    except Exception as exc:
        _log.warning("retry_budget._rotation_target failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
class _RetryBudget:
    def __init__(self):
        self._lock = threading.Lock()
        self._cache = {}          # prefix -> {attempt_num -> {total, success}}
        self._cache_ts = 0.0
        self._error_cache = {}    # prefix -> {error_class -> {total, retried_success}}
        self._inmemory = {}       # prefix -> {attempt_num -> {total, success}}
        self._inmemory_errors = {}  # prefix -> {error_class -> {total, retried_success}}
        self._saved_attempts = 0
        self._tokens_saved = 0

    # ----- cache refresh ---------------------------------------------------
    def _refresh(self):
        now = time.time()
        if now - self._cache_ts < TTL:
            return
        try:
            rows = db.select("outcomes", {
                "select": "slug,model,attempts,tests_passed,integrated,note",
                "limit": "10000",
            }) or []
            agg = {}       # prefix -> {attempt_num -> {total, success}}
            err_agg = {}   # prefix -> {error_class -> {total, retried_success}}
            for r in rows:
                prefix = _slug_prefix(r.get("slug") or "")
                attempt = int(r.get("attempts") or 1)
                success = bool(r.get("integrated") or r.get("tests_passed"))

                bucket = agg.setdefault(prefix, {}).setdefault(attempt, {"total": 0, "success": 0})
                bucket["total"] += 1
                if success:
                    bucket["success"] += 1

                # Track error recovery patterns.  This loop body used to be an empty
                # comment, so err_agg was always {} and _merged_error_stats() could
                # only ever see in-memory data from the current process — the
                # "retries never helped for prefix/error_class" branch in
                # should_retry() was unreachable across restarts.
                err_class = _classify_error(r.get("note") or "")
                # Provider exhaustion carries no signal about the task; excluding it
                # keeps the historical retry-effectiveness figure honest.
                if err_class == "provider_exhausted":
                    continue
                eb = err_agg.setdefault(prefix, {}).setdefault(
                    err_class, {"total": 0, "retried_success": 0})
                eb["total"] += 1
                if success and attempt > 1:
                    eb["retried_success"] += 1

            self._cache = agg
            self._error_cache = err_agg
            self._cache_ts = now
        except Exception as exc:
            _log.warning("retry_budget refresh failed: %s", exc)

    def _merged_stats(self, prefix):
        """Merge DB-cache and in-memory stats for a prefix."""
        merged = {}
        for src in (self._cache.get(prefix, {}), self._inmemory.get(prefix, {})):
            for attempt_num, bucket in src.items():
                m = merged.setdefault(attempt_num, {"total": 0, "success": 0})
                m["total"] += bucket["total"]
                m["success"] += bucket["success"]
        return merged

    def _merged_error_stats(self, prefix):
        """Merge DB-cache and in-memory error stats for a prefix."""
        merged = {}
        for src in (self._error_cache.get(prefix, {}), self._inmemory_errors.get(prefix, {})):
            for err_class, bucket in src.items():
                m = merged.setdefault(err_class, {"total": 0, "retried_success": 0})
                m["total"] += bucket["total"]
                m["retried_success"] += bucket["retried_success"]
        return merged

    # ----- public API ------------------------------------------------------
    def max_attempts(self, task):
        """Return the recommended max attempts (1-4) for a task."""
        if not ENABLED:
            return DEFAULT_MAX
        try:
            with self._lock:
                self._refresh()
                slug = task.get("slug") or task.get("id") or ""
                prefix = _slug_prefix(slug)
                stats = self._merged_stats(prefix)

                # Never-seen prefix -> default
                if not stats:
                    # Still check complexity
                    complexity = _get_complexity(task)
                    if complexity in _LOW_COMPLEXITY:
                        return min(2, DEFAULT_MAX)
                    return DEFAULT_MAX

                # Check attempt-1 success rate
                a1 = stats.get(1, {"total": 0, "success": 0})
                if a1["total"] >= 5:
                    a1_rate = a1["success"] / a1["total"]
                    # >90% first-attempt success -> cap at 2 (rarely needs deep retry)
                    if a1_rate > 0.9:
                        _log.debug("prefix=%s a1_rate=%.2f -> cap=2", prefix, a1_rate)
                        return 2

                # Check attempt 3+ success rate
                late_total = 0
                late_success = 0
                for attempt_num, bucket in stats.items():
                    if attempt_num >= 3:
                        late_total += bucket["total"]
                        late_success += bucket["success"]
                if late_total >= 3 and late_success == 0:
                    # 0% success at attempt 3+ -> cap at 2
                    _log.debug("prefix=%s late_attempts=%d late_success=0 -> cap=2", prefix, late_total)
                    return 2

                # Check complexity from ai_review
                complexity = _get_complexity(task)
                if complexity in _LOW_COMPLEXITY:
                    return min(2, DEFAULT_MAX)
                if complexity in _HIGH_COMPLEXITY:
                    return DEFAULT_MAX  # full retries for complex work

                return DEFAULT_MAX
        except Exception as exc:
            _log.warning("retry_budget.max_attempts failed: %s — returning default %d", exc, DEFAULT_MAX)
            return DEFAULT_MAX

    def should_retry(self, task, attempt, last_error):
        """Decide whether to retry a task after a failure.

        Returns {"retry": bool, "reason": str, "recommended_model": Optional[str]}.
        """
        if not ENABLED:
            return {"retry": attempt < DEFAULT_MAX, "reason": "budget disabled, using default", "recommended_model": None}
        try:
            with self._lock:
                self._refresh()
                slug = task.get("slug") or task.get("id") or ""
                prefix = _slug_prefix(slug)
                error_class = _classify_error(last_error)
                max_att = self._max_attempts_unlocked(task)

                # Provider exhaustion must be tested BEFORE the budget cap.  The
                # provider refused at the API boundary (403 credits/spending limit),
                # so no coder ever ran and the attempt carries no signal about the
                # task.  Charging it to the budget is how a task with zero real
                # attempts ends up BLOCKED with "reached budget cap (4)" — the exact
                # failure that produced this fix.  Rotate providers instead; the
                # caller reads recommended_model to pick a different route.
                if error_class == "provider_exhausted":
                    return {
                        "retry": True,
                        "reason": ("provider budget/credits exhausted — does not consume the "
                                   "retry budget; rotate to a different provider"),
                        "recommended_model": _rotation_target(task),
                    }

                if attempt >= max_att:
                    return {"retry": False, "reason": f"reached budget cap ({max_att})", "recommended_model": None}

                # Rate limit errors: always retry
                if error_class == "rate_limit":
                    return {"retry": True, "reason": "rate_limit error — always retry", "recommended_model": None}

                # Timeout errors: retry with a note about higher budget
                if error_class == "timeout":
                    return {"retry": True, "reason": "timeout — retry with extended budget", "recommended_model": None}

                # Assertion errors: retry, suggest constraint injection
                if error_class == "assertion":
                    return {"retry": True, "reason": "assertion failure — retry with constraint injection", "recommended_model": None}

                # Check if retries have historically helped for this prefix+error
                err_stats = self._merged_error_stats(prefix)
                ec_bucket = err_stats.get(error_class) or err_stats.get("other")
                if ec_bucket and ec_bucket["total"] >= 3:
                    retry_rate = ec_bucket["retried_success"] / ec_bucket["total"]
                    if retry_rate == 0:
                        return {"retry": False, "reason": f"retries never helped for {prefix}/{error_class} (n={ec_bucket['total']})", "recommended_model": None}

                # Default: retry
                return {"retry": True, "reason": f"attempt {attempt}/{max_att}, error_class={error_class}", "recommended_model": None}
        except Exception as exc:
            _log.warning("retry_budget.should_retry failed: %s — allowing retry", exc)
            return {"retry": attempt < DEFAULT_MAX, "reason": f"error in budget check: {exc}", "recommended_model": None}

    def _max_attempts_unlocked(self, task):
        """max_attempts logic without re-acquiring the lock (for internal use)."""
        slug = task.get("slug") or task.get("id") or ""
        prefix = _slug_prefix(slug)
        stats = self._merged_stats(prefix)

        if not stats:
            complexity = _get_complexity(task)
            if complexity in _LOW_COMPLEXITY:
                return min(2, DEFAULT_MAX)
            return DEFAULT_MAX

        a1 = stats.get(1, {"total": 0, "success": 0})
        if a1["total"] >= 5 and a1["success"] / a1["total"] > 0.9:
            return 2

        late_total = 0
        late_success = 0
        for attempt_num, bucket in stats.items():
            if attempt_num >= 3:
                late_total += bucket["total"]
                late_success += bucket["success"]
        if late_total >= 3 and late_success == 0:
            return 2

        complexity = _get_complexity(task)
        if complexity in _LOW_COMPLEXITY:
            return min(2, DEFAULT_MAX)

        return DEFAULT_MAX

    def record_attempt(self, slug, attempt, model, success, error_class=None):
        """Record the outcome of an attempt for future budget decisions."""
        try:
            with self._lock:
                prefix = _slug_prefix(slug)
                # A provider-exhausted attempt never reached the coder, so counting it
                # as a failed attempt for this prefix would depress the prefix's
                # success rate and make _max_attempts_unlocked cap future, unrelated
                # tasks at 2 on the strength of a billing problem.
                if error_class == "provider_exhausted":
                    _log.debug("record_attempt: prefix=%s attempt=%d not charged "
                               "(provider exhausted)", prefix, attempt)
                    return
                bucket = self._inmemory.setdefault(prefix, {}).setdefault(
                    attempt, {"total": 0, "success": 0})
                bucket["total"] += 1
                if success:
                    bucket["success"] += 1

                # Track error patterns
                if error_class:
                    eb = self._inmemory_errors.setdefault(prefix, {}).setdefault(
                        error_class, {"total": 0, "retried_success": 0})
                    eb["total"] += 1
                    if success and attempt > 1:
                        eb["retried_success"] += 1

                # Track savings when we capped retries and it was the right call
                if success and attempt == 1:
                    # First-attempt success on a capped task = saved attempts
                    all_stats = self._merged_stats(prefix)
                    a1 = all_stats.get(1, {"total": 0, "success": 0})
                    if a1["total"] >= 5 and a1["success"] / max(1, a1["total"]) > 0.9:
                        self._saved_attempts += 2  # would have reserved 4, capped to 2
                        self._tokens_saved += 50000  # rough estimate per saved attempt

                _log.debug("recorded attempt: prefix=%s attempt=%d success=%s error=%s",
                           prefix, attempt, success, error_class)
        except Exception as exc:
            _log.warning("retry_budget.record_attempt failed: %s", exc)

    def stats(self):
        """Return retry budget statistics."""
        try:
            with self._lock:
                self._refresh()

                # Compute retry effectiveness by attempt number
                effectiveness = {}
                all_prefixes = set(list(self._cache.keys()) + list(self._inmemory.keys()))
                agg_by_attempt = {}  # attempt_num -> {total, success}
                for prefix in all_prefixes:
                    merged = self._merged_stats(prefix)
                    for attempt_num, bucket in merged.items():
                        a = agg_by_attempt.setdefault(attempt_num, {"total": 0, "success": 0})
                        a["total"] += bucket["total"]
                        a["success"] += bucket["success"]

                for attempt_num in sorted(agg_by_attempt.keys()):
                    bucket = agg_by_attempt[attempt_num]
                    rate = bucket["success"] / max(1, bucket["total"])
                    effectiveness[attempt_num] = {
                        "total": bucket["total"],
                        "success": bucket["success"],
                        "rate": round(rate, 3),
                    }

                return {
                    "total_saved_attempts": self._saved_attempts,
                    "tokens_saved_estimate": self._tokens_saved,
                    "retry_effectiveness": effectiveness,
                    "prefixes_tracked": len(all_prefixes),
                    "enabled": ENABLED,
                    "default_max": DEFAULT_MAX,
                }
        except Exception as exc:
            _log.warning("retry_budget.stats failed: %s", exc)
            return {
                "total_saved_attempts": 0,
                "tokens_saved_estimate": 0,
                "retry_effectiveness": {},
                "prefixes_tracked": 0,
                "enabled": ENABLED,
                "default_max": DEFAULT_MAX,
            }


# ---------------------------------------------------------------------------
# Module-level singleton + delegating functions
# ---------------------------------------------------------------------------
_instance = _RetryBudget()


def max_attempts(task):
    """Return the recommended max attempts (1-4) for a task dict."""
    return _instance.max_attempts(task)


def should_retry(task, attempt, last_error):
    """Decide whether to retry.  Returns {retry, reason, recommended_model}."""
    return _instance.should_retry(task, attempt, last_error)


def record_attempt(slug, attempt, model, success, error_class=None):
    """Record the outcome of an attempt for future budget decisions."""
    _instance.record_attempt(slug, attempt, model, success, error_class)


def stats():
    """Return retry budget statistics dict."""
    return _instance.stats()
