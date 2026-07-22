#!/usr/bin/env python3
"""
auto_error_categorizer.py - automated error categorization with learning.

Builds on error_taxonomy.py by adding:
  - Automatic transient-vs-permanent classification with confidence scores
  - A learning feedback loop: record whether a retried error eventually succeeded
    or remained permanent, and use that history to improve future classification
  - Bulk categorization for batch error analysis
  - Error fingerprinting to group similar errors regardless of variable details

Fail-soft: all public functions return sensible defaults on internal errors.
Thread-safe.

Env vars:
    ORCH_AUTO_CATEGORIZER_ENABLED   default "true"
    ORCH_CATEGORIZER_HISTORY_SIZE   default 500
"""
import os, sys, re, time, hashlib, threading, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ENABLED = os.environ.get("ORCH_AUTO_CATEGORIZER_ENABLED", "true").lower() in ("1", "true", "yes")
HISTORY_SIZE = int(os.environ.get("ORCH_CATEGORIZER_HISTORY_SIZE", "500"))

# ---------- Error categories ----------

TRANSIENT = "transient"
PERMANENT = "permanent"
AMBIGUOUS = "ambiguous"

# ---------- Fingerprinting ----------

# Patterns to normalize before fingerprinting (strip variable parts)
_VARIABLE_PATTERNS = [
    (re.compile(r"\b\d{10,}\b"), "<TIMESTAMP>"),          # unix timestamps
    (re.compile(r"\b[0-9a-f]{8,}\b", re.I), "<HEX>"),    # hex hashes/ids
    (re.compile(r"\b\d+\.\d+\.\d+\.\d+\b"), "<IP>"),     # IP addresses
    (re.compile(r":\d{2,5}\b"), ":<PORT>"),                # ports
    (re.compile(r"\bline \d+\b", re.I), "line <N>"),      # line numbers
    (re.compile(r"\btask[_-]?\d+\b", re.I), "task<N>"),   # task IDs
    (re.compile(r"/tmp/[^\s]+"), "<TMPPATH>"),             # temp paths
]


def fingerprint(error_text):
    """Generate a stable fingerprint for an error message.

    Strips variable details (timestamps, IDs, line numbers) so that
    structurally identical errors map to the same fingerprint.

    Returns (fingerprint_hex, normalized_text).
    """
    try:
        text = str(error_text or "").strip()
        normalized = text
        for pattern, replacement in _VARIABLE_PATTERNS:
            normalized = pattern.sub(replacement, normalized)
        # Collapse whitespace
        normalized = re.sub(r"\s+", " ", normalized).strip()
        fp = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:12]
        return fp, normalized
    except Exception:
        return "000000000000", str(error_text)[:200]


# ---------- Classification ----------

_TRANSIENT_PATTERNS = re.compile(
    r"(?i)(connection\s*(reset|refused|error|timeout)|"
    r"timeout|timed?\s*out|rate.?limit|429|503|502|500|"
    r"overload|temporarily|service unavailable|"
    r"budget cap|try again|econnreset|econnrefused|"
    r"broken pipe|reset by peer|network|dns|"
    r"too many requests|throttl|quota exceeded|"
    r"resource_exhausted|high demand|"
    r"read timed out|write timed out)"
)

_PERMANENT_PATTERNS = re.compile(
    r"(?i)(syntax\s*error|type\s*error|name\s*error|"
    r"attribute\s*error|import\s*error|module\s*not\s*found|"
    r"permission\s*denied|forbidden|unauthorized|"
    r"invalid\s*(argument|parameter|input|config)|"
    r"not\s*found|does\s*not\s*exist|"
    r"assertion\s*error|test.*fail|"
    r"merge\s*conflict|"
    r"schema.*violation|constraint.*violation|"
    r"cannot\s*import|no\s*such\s*file)"
)

# ---------- Learning state ----------

_lock = threading.Lock()
_feedback_history = {}   # fingerprint -> {"transient_ok": int, "transient_fail": int, "permanent": int}
_classification_log = []  # recent classifications for debugging


def categorize(error_text, context=None):
    """Categorize an error as transient, permanent, or ambiguous.

    Returns dict with:
        category: "transient" | "permanent" | "ambiguous"
        confidence: 0.0 - 1.0
        fingerprint: stable hash for grouping
        normalized: cleaned error text
        retryable: bool (True if transient)
        recommendation: str
    """
    try:
        if not ENABLED:
            return _default_result(error_text)

        text = str(error_text or "")
        fp, normalized = fingerprint(text)

        # Check learned history first
        learned = _check_history(fp)
        if learned is not None:
            return learned

        # Static pattern matching
        is_transient = bool(_TRANSIENT_PATTERNS.search(text))
        is_permanent = bool(_PERMANENT_PATTERNS.search(text))

        if is_transient and not is_permanent:
            category, confidence = TRANSIENT, 0.85
        elif is_permanent and not is_transient:
            category, confidence = PERMANENT, 0.85
        elif is_transient and is_permanent:
            # Both match — ambiguous, lean permanent (safer)
            category, confidence = AMBIGUOUS, 0.50
        else:
            # Neither matches
            category, confidence = AMBIGUOUS, 0.30

        result = {
            "category": category,
            "confidence": confidence,
            "fingerprint": fp,
            "normalized": normalized[:200],
            "retryable": category == TRANSIENT,
            "recommendation": _recommend(category),
        }

        _record_classification(fp, result)
        return result

    except Exception:
        return _default_result(error_text)


def categorize_batch(errors):
    """Categorize a list of error texts. Returns list of categorization results."""
    try:
        return [categorize(e) for e in (errors or [])]
    except Exception:
        return []


def record_feedback(error_text, retry_succeeded):
    """Record whether retrying a transient error succeeded or failed.

    This feeds the learning loop so future classifications improve.
    """
    try:
        fp, _ = fingerprint(error_text)
        with _lock:
            if fp not in _feedback_history:
                _feedback_history[fp] = {"transient_ok": 0, "transient_fail": 0, "permanent": 0}
            if retry_succeeded:
                _feedback_history[fp]["transient_ok"] += 1
            else:
                _feedback_history[fp]["transient_fail"] += 1
            # Cap history size
            if len(_feedback_history) > HISTORY_SIZE:
                oldest = list(_feedback_history.keys())[0]
                del _feedback_history[oldest]
    except Exception:
        pass


def _check_history(fp):
    """Check if we have learned feedback for this fingerprint."""
    with _lock:
        h = _feedback_history.get(fp)
    if not h:
        return None
    total = h["transient_ok"] + h["transient_fail"] + h["permanent"]
    if total < 2:
        return None  # not enough data
    success_rate = h["transient_ok"] / max(1, h["transient_ok"] + h["transient_fail"])
    if success_rate > 0.6:
        return {
            "category": TRANSIENT, "confidence": min(0.95, 0.7 + success_rate * 0.2),
            "fingerprint": fp, "normalized": "(learned)", "retryable": True,
            "recommendation": "retry (learned from history)",
        }
    elif h["transient_fail"] > h["transient_ok"] * 2:
        return {
            "category": PERMANENT, "confidence": 0.80,
            "fingerprint": fp, "normalized": "(learned)", "retryable": False,
            "recommendation": "do not retry (learned from history)",
        }
    return None


def _recommend(category):
    return {
        TRANSIENT: "retry with exponential backoff",
        PERMANENT: "do not retry; requires human review or code fix",
        AMBIGUOUS: "retry once cautiously; escalate if it recurs",
    }.get(category, "unknown")


def _default_result(error_text):
    fp, normalized = fingerprint(error_text)
    return {
        "category": AMBIGUOUS, "confidence": 0.0,
        "fingerprint": fp, "normalized": normalized[:200],
        "retryable": False, "recommendation": "unknown error; manual review",
    }


def _record_classification(fp, result):
    with _lock:
        _classification_log.append({"fp": fp, "category": result["category"],
                                     "ts": time.time()})
        if len(_classification_log) > HISTORY_SIZE:
            _classification_log.pop(0)


def stats():
    """Return classification statistics."""
    with _lock:
        cats = {}
        for entry in _classification_log:
            c = entry["category"]
            cats[c] = cats.get(c, 0) + 1
        return {
            "total_classified": len(_classification_log),
            "by_category": cats,
            "feedback_entries": len(_feedback_history),
        }


def clear():
    """Reset all state."""
    with _lock:
        _feedback_history.clear()
        _classification_log.clear()
