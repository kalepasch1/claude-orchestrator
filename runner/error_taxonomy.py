#!/usr/bin/env python3
"""
error_taxonomy.py - classify errors from task execution and select targeted
remediation strategies instead of blind retry with model escalation.

Each error class maps to a specific remediation action:
    rate_limit      -> wait_and_retry     (wait 60s, same model)
    exhaustion      -> rotate_account     (switch to next account)
    test_failure    -> constrain_retry    (extract failures as constraints)
    merge_conflict  -> rebase_retry       (rebase onto latest, retry)
    import_error    -> dependency_fix     (install missing deps, retry)
    syntax_error    -> lint_retry         (add lint step to prompt)
    timeout         -> budget_increase    (increase timeout/token budget)
    build_failure   -> build_fix          (extract build errors as constraints)
    permission_error-> skip              (mark BLOCKED)
    unknown         -> escalate_model     (escalate one tier)

Thread-safe, fail-soft.  Env: ORCH_ERROR_TAXONOMY_ENABLED (default "true").
"""
import sys, os, re, json, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("error_taxonomy")

# ---------------------------------------------------------------------------
# Feature gate
# ---------------------------------------------------------------------------
_ENABLED = os.environ.get("ORCH_ERROR_TAXONOMY_ENABLED", "true").lower() in ("true", "1", "yes")

# ---------------------------------------------------------------------------
# Classification patterns (compiled once)
# ---------------------------------------------------------------------------
_PATTERNS = [
    # (error_class, subclass, compiled_regex, confidence)
    ("rate_limit", "429",
     re.compile(r"(?i)(rate.?limit|429|too many requests|throttl|quota exceeded|resource_exhausted)", re.S), 0.95),
    ("exhaustion", "account_quota",
     re.compile(r"(?i)(insufficient.?quota|billing|credit|payment.?required|account.?(suspend|disabl))", re.S), 0.90),
    ("test_failure", "assertion",
     re.compile(r"(?i)(FAIL(ED)?:?\s|assert(ion)?.*error|test.*fail|pytest|unittest.*fail|expect.*to\s)", re.S), 0.90),
    ("merge_conflict", "git",
     re.compile(r"(CONFLICT|<{7}\s|>{7}\s|merge conflict|cannot merge|rebase.*fail)", re.S), 0.92),
    ("import_error", "module_not_found",
     re.compile(r"(?i)(ModuleNotFoundError|ImportError|No module named|cannot import name)", re.S), 0.93),
    ("syntax_error", "parse",
     re.compile(r"(?i)(SyntaxError|IndentationError|unexpected token|parsing error|unterminated string)", re.S), 0.92),
    ("timeout", "execution",
     re.compile(r"(?i)(timed?\s*out|timeout|deadline exceeded|execution.*expired|max.*token.*reached)", re.S), 0.88),
    ("build_failure", "compile",
     re.compile(r"(?i)(build fail|compilation error|linker error|make.*error|npm ERR|cargo.*error|tsc.*error)", re.S), 0.88),
    ("permission_error", "access",
     re.compile(r"(?i)(permission denied|access denied|forbidden|EACCES|not authorized|403)", re.S), 0.90),
]

_CLASS_TO_REMEDIATION = {
    "rate_limit":       "wait_and_retry",
    "exhaustion":       "rotate_account",
    "test_failure":     "constrain_retry",
    "merge_conflict":   "rebase_retry",
    "import_error":     "dependency_fix",
    "syntax_error":     "lint_retry",
    "timeout":          "budget_increase",
    "build_failure":    "build_fix",
    "permission_error": "skip",
    "unknown":          "escalate_model",
}

# ---------------------------------------------------------------------------
# Singleton state (thread-safe)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_error_counts = {}          # {error_class: int}
_remediation_outcomes = {}  # {(error_class, remediation): {"success": int, "failure": int}}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify(error_text, task=None):
    """Classify *error_text* and return remediation advice.

    Returns {"error_class", "subclass", "confidence", "remediation"}.
    """
    if not _ENABLED:
        return {"error_class": "unknown", "subclass": "disabled",
                "confidence": 0.0, "remediation": "escalate_model"}
    try:
        text = str(error_text or "")
        for err_cls, sub, pattern, conf in _PATTERNS:
            if pattern.search(text):
                _increment(err_cls)
                return {"error_class": err_cls, "subclass": sub,
                        "confidence": conf,
                        "remediation": _CLASS_TO_REMEDIATION[err_cls]}
        _increment("unknown")
        return {"error_class": "unknown", "subclass": "no_match",
                "confidence": 0.3, "remediation": "escalate_model"}
    except Exception as exc:
        _log.debug("classify error: %s", exc)
        return {"error_class": "unknown", "subclass": "classify_error",
                "confidence": 0.0, "remediation": "escalate_model"}


def remediation_prompt(error_class, error_text, task=None):
    """Return a prompt section tailored to the error type."""
    try:
        text = str(error_text or "")
        task_slug = ""
        if task:
            task_slug = task.get("slug", "") if isinstance(task, dict) else str(task)

        if error_class == "test_failure":
            failures = _extract_test_failures(text)
            constraint = "\n".join(f"  - {f}" for f in failures) if failures else text[:500]
            return (
                f"The previous attempt for '{task_slug}' failed these tests:\n"
                f"{constraint}\n\n"
                "Fix ONLY the code that caused these specific test failures. "
                "Do not change test files unless the tests themselves are wrong."
            )

        if error_class == "merge_conflict":
            files = _extract_conflict_files(text)
            file_list = ", ".join(files) if files else "(see error output)"
            return (
                f"The previous attempt for '{task_slug}' hit merge conflicts in: {file_list}\n\n"
                "Rebase onto the latest base branch, resolve conflicts preserving "
                "upstream changes, then re-apply your modifications."
            )

        if error_class == "build_failure":
            errors = _extract_build_errors(text)
            detail = "\n".join(f"  - {e}" for e in errors) if errors else text[:500]
            return (
                f"The previous attempt for '{task_slug}' failed to build:\n"
                f"{detail}\n\n"
                "Fix the build errors above before proceeding."
            )

        if error_class == "import_error":
            modules = re.findall(r"No module named ['\"]?(\S+)['\"]?", text)
            mod_list = ", ".join(modules) if modules else "(see error)"
            return (
                f"Missing dependencies: {mod_list}. "
                "Install them (pip/npm/etc.) and retry."
            )

        if error_class == "syntax_error":
            return (
                f"The previous attempt for '{task_slug}' produced a syntax error. "
                "Before submitting, run the linter and fix all syntax issues. "
                "Error details:\n" + text[:500]
            )

        if error_class == "rate_limit":
            return "Rate-limited. Wait 60 seconds and retry with the same model."

        if error_class == "exhaustion":
            return "Account quota exhausted. Rotate to the next available account."

        if error_class == "timeout":
            return (
                f"The previous attempt for '{task_slug}' timed out. "
                "Increase the timeout or token budget and retry."
            )

        if error_class == "permission_error":
            return (
                f"Permission denied for '{task_slug}'. "
                "This task cannot proceed without elevated access. Marking BLOCKED."
            )

        # unknown / fallback
        return (
            f"The previous attempt for '{task_slug}' failed with an unclassified error. "
            "Escalate to a more capable model.\n\nError excerpt:\n" + text[:400]
        )
    except Exception as exc:
        _log.debug("remediation_prompt error: %s", exc)
        return ""


def record_remediation(error_class, remediation, success):
    """Track whether a remediation action led to success."""
    try:
        key = (str(error_class), str(remediation))
        with _lock:
            if key not in _remediation_outcomes:
                _remediation_outcomes[key] = {"success": 0, "failure": 0}
            if success:
                _remediation_outcomes[key]["success"] += 1
            else:
                _remediation_outcomes[key]["failure"] += 1
    except Exception as exc:
        _log.debug("record_remediation error: %s", exc)


def stats():
    """Return error distribution and remediation success rates."""
    try:
        with _lock:
            dist = dict(_error_counts)
            rates = {}
            for (ecls, rem), counts in _remediation_outcomes.items():
                total = counts["success"] + counts["failure"]
                rate = counts["success"] / total if total else 0.0
                rates[f"{ecls}/{rem}"] = {
                    "success": counts["success"],
                    "failure": counts["failure"],
                    "total": total,
                    "success_rate": round(rate, 3),
                }
        return {"error_distribution": dist, "remediation_success_rates": rates}
    except Exception:
        return {"error_distribution": {}, "remediation_success_rates": {}}


def effectiveness():
    """Compare targeted remediations vs the old blind-escalate approach.

    Returns per-class success rates alongside what the fallback ('escalate_model')
    achieves, so operators can see which targeted strategies outperform.
    """
    try:
        with _lock:
            per_class = {}
            escalate_s = 0
            escalate_f = 0
            for (ecls, rem), counts in _remediation_outcomes.items():
                total = counts["success"] + counts["failure"]
                if not total:
                    continue
                rate = counts["success"] / total
                if rem == "escalate_model":
                    escalate_s += counts["success"]
                    escalate_f += counts["failure"]
                entry = per_class.setdefault(ecls, {})
                entry[rem] = {"success_rate": round(rate, 3), "n": total}
            escalate_total = escalate_s + escalate_f
            baseline = round(escalate_s / escalate_total, 3) if escalate_total else None
        return {"per_class": per_class, "escalate_baseline": baseline}
    except Exception:
        return {"per_class": {}, "escalate_baseline": None}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _increment(error_class):
    with _lock:
        _error_counts[error_class] = _error_counts.get(error_class, 0) + 1


def _extract_test_failures(text):
    """Pull assertion messages and failed test names from output."""
    failures = []
    # pytest-style: FAILED tests/test_foo.py::test_bar
    failures.extend(re.findall(r"FAILED\s+(\S+)", text))
    # AssertionError: ...
    failures.extend(re.findall(r"Assertion(?:Error)?:\s*(.+?)(?:\n|$)", text))
    # unittest: FAIL: test_bar (test_foo.TestClass)
    failures.extend(re.findall(r"FAIL:\s+(\S+.*?)(?:\n|$)", text))
    return failures[:20]  # cap to keep prompt manageable


def _extract_conflict_files(text):
    """Pull conflicting file paths from git merge/rebase output."""
    files = re.findall(r"CONFLICT.*?:\s*(?:Merge conflict in\s+)?(\S+)", text)
    return list(dict.fromkeys(files))[:20]


def _extract_build_errors(text):
    """Pull compiler/build error lines."""
    errors = []
    # generic "error:" lines (gcc, clang, tsc, rustc)
    errors.extend(re.findall(r"^.*error[:\[].*$", text, re.M))
    # npm ERR! lines
    errors.extend(re.findall(r"^npm ERR!.*$", text, re.M))
    return errors[:20]
