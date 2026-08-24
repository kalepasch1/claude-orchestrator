"""AI-powered error classification and remediation suggestions.

Classifies runner errors into categories and suggests remediation steps.
Pure heuristic functions — no external API calls. Fail-soft: returns
sensible defaults on any bad input (None, empty, malformed).
"""

import os
import re
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration (env-var overrides)
# ---------------------------------------------------------------------------
MAX_CONTEXT_LINES = int(os.environ.get("ORCH_ERROR_MAX_CONTEXT_LINES", "10"))
HIGH_CONFIDENCE_THRESHOLD = float(
    os.environ.get("ORCH_ERROR_HIGH_CONFIDENCE", "0.8")
)

# ---------------------------------------------------------------------------
# Pattern registry — (compiled_regex, category, confidence)
# ---------------------------------------------------------------------------
_PATTERNS: list[tuple[re.Pattern, str, float]] = [
    # billing / quota exhaustion — MUST precede auth and resource.
    #
    # A provider that answers "403 permission-denied: your team has used all available
    # credits" matches the auth pattern (403) at 0.90 confidence, and auth was a
    # transient category, so the runner retried it at 4s, 8s, 16s and 32s and then
    # failed anyway. Sixty seconds burned per task, and identically for every
    # subsequent task routed to that provider, because no amount of waiting adds
    # credits to an account. This is the failure that exhausted retries on
    # improve-distribute-test-runners-across-fleet-8-slice-3.
    #
    # Ordering is load-bearing: classify_error returns the FIRST match, so these must
    # sit above both the auth 403 rule and the resource "quota exceeded" rule.
    (re.compile(r"used all available credits|purchase more credits|"
                r"spending limit|billing (?:hard )?limit|"
                r"insufficient (?:credit|funds|quota|balance)|"
                r"payment required|402\b", re.I), "billing", 0.95),
    (re.compile(r"(?:credit|quota)s? (?:exhausted|depleted|used up)|"
                r"exceeded your current quota|out of credits", re.I), "billing", 0.92),

    # dependency / import
    (re.compile(r"ModuleNotFoundError|ImportError|No module named", re.I), "dependency", 0.95),
    (re.compile(r"package .* not found|pip install|requirements\.txt", re.I), "dependency", 0.85),
    (re.compile(r"cannot import name", re.I), "dependency", 0.80),

    # auth — expiry rules FIRST.
    #
    # classify_error returns the first match and reports it as `pattern`, which is the
    # only evidence is_transient gets. "401: token expired" matching the numeric rule
    # first would report pattern="401" and throw away the one detail that makes it
    # retryable, so the specific rule has to win.
    (re.compile(r"token(?:s)? (?:has )?expired|expired token|session expired|"
                r"credential(?:s)? expired", re.I), "auth", 0.90),
    (re.compile(r"401|403|Unauthorized|Forbidden|AuthenticationError", re.I), "auth", 0.90),
    (re.compile(r"invalid token|permission denied", re.I), "auth", 0.88),
    (re.compile(r"Access Denied|credentials", re.I), "auth", 0.75),

    # timeout
    (re.compile(r"TimeoutError|timed? ?out|deadline exceeded", re.I), "timeout", 0.92),
    (re.compile(r"connect(?:ion)? timed? ?out|read timed? ?out|ETIMEDOUT", re.I), "timeout", 0.90),
    (re.compile(r"socket\.timeout|asyncio\.TimeoutError", re.I), "timeout", 0.88),

    # syntax
    (re.compile(r"SyntaxError|IndentationError|TabError", re.I), "syntax", 0.95),
    (re.compile(r"unexpected token|parse error|invalid syntax", re.I), "syntax", 0.85),

    # resource
    (re.compile(r"MemoryError|OOMKilled|Cannot allocate memory", re.I), "resource", 0.95),
    (re.compile(r"disk full|No space left on device|ENOSPC", re.I), "resource", 0.93),
    (re.compile(r"too many open files|EMFILE|ulimit", re.I), "resource", 0.85),
    (re.compile(r"ResourceExhausted|quota exceeded", re.I), "resource", 0.88),

    # runtime (broad — must come after more specific categories)
    (re.compile(r"Traceback \(most recent call last\)", re.I), "runtime", 0.70),
    (re.compile(r"TypeError|ValueError|KeyError|AttributeError|IndexError", re.I), "runtime", 0.82),
    (re.compile(r"RuntimeError|AssertionError|NotImplementedError", re.I), "runtime", 0.80),
    (re.compile(r"Exception|Error", re.I), "runtime", 0.50),
]

# Transient categories — worth an automatic retry.
#
# `auth` is deliberately NOT here any more. It covered both "the token expired, refresh
# and it works" and "this account is not allowed to do this, ever", and the retry loop
# could not tell them apart — so every hard 403 cost four backoff sleeps before failing.
# Token expiry is still retried, via _RETRYABLE_AUTH below, which requires positive
# evidence of expiry rather than assuming it.
_TRANSIENT_CATEGORIES = {"timeout", "resource"}

# Auth errors worth one retry: a credential that WAS valid and aged out. Anything else
# (permission denied, forbidden, invalid key) needs a human, not a sleep.
_RETRYABLE_AUTH = re.compile(
    r"token expired|expired token|session expired|token has expired|"
    r"credential(?:s)? expired|refresh(?:ing)? the token", re.I)

# Categories that can never be fixed by waiting. Retrying them is pure cost: the runner
# burns its backoff budget and the task fails in exactly the same way.
_PERMANENT_CATEGORIES = {"billing"}

# Severity ordering (lower index = higher severity)
_SEVERITY_ORDER = ["billing", "resource", "auth", "syntax", "dependency", "timeout",
                   "runtime", "unknown"]

# ---------------------------------------------------------------------------
# Remediation lookup
# ---------------------------------------------------------------------------
_REMEDIATIONS: dict[str, list[str]] = {
    "dependency": [
        "Run `pip install -r requirements.txt` (or the project's install command).",
        "Check that the virtual-env is activated.",
        "Verify the module name matches the package name on PyPI.",
        "Pin the version in requirements if a breaking update landed.",
    ],
    "auth": [
        "Refresh or rotate the expired token/credential.",
        "Verify the service account has the required permissions.",
        "Check that ORCH_ env vars for secrets are set on this machine.",
        "If 403: confirm IP allow-lists or network ACLs.",
    ],
    "timeout": [
        "Retry — timeouts are often transient.",
        "Increase the timeout budget (ORCH_TIMEOUT_SEC).",
        "Check upstream service health / network connectivity.",
    ],
    "syntax": [
        "Fix the syntax error at the reported file:line.",
        "Run a linter / `python -m py_compile <file>` to catch additional issues.",
        "Check for mixed tabs/spaces if IndentationError.",
    ],
    "runtime": [
        "Read the traceback bottom-up to find the root cause.",
        "Add defensive guards (None-checks, key existence) around the failing line.",
        "Check recent commits that touched the failing module.",
    ],
    "resource": [
        "Free memory or disk on the runner machine.",
        "Reduce batch size / concurrency.",
        "Check for memory leaks in long-running processes.",
        "If OOMKilled: increase container memory limit.",
    ],
    "billing": [
        "STOP RETRYING — no amount of backoff adds credits to an account.",
        "Add credits or raise the spending limit for the failing provider.",
        "Until then, take that provider out of the routing rotation so tasks are not "
        "routed into a guaranteed failure.",
        "Check whether other tasks are failing the same way: one exhausted provider "
        "fails every task routed to it, not just this one.",
    ],
    "unknown": [
        "Inspect the full error log for context.",
        "Search the error message in the project issue tracker.",
        "Escalate to a human operator if repeated.",
    ],
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_error(error_text: str) -> dict:
    """Classify *error_text* into a category with confidence.

    Returns ``{"category": str, "confidence": float, "pattern": str}``.
    Fail-soft: bad input → category ``"unknown"`` with confidence 0.
    """
    if not error_text or not isinstance(error_text, str):
        return {"category": "unknown", "confidence": 0.0, "pattern": ""}

    for pattern, category, confidence in _PATTERNS:
        match = pattern.search(error_text)
        if match:
            return {
                "category": category,
                "confidence": confidence,
                "pattern": match.group(0),
            }

    return {"category": "unknown", "confidence": 0.0, "pattern": ""}


def suggest_remediation(classification: dict) -> list[str]:
    """Return ordered remediation steps for *classification*.

    Accepts the dict returned by :func:`classify_error`.
    Fail-soft: bad input → generic advice.
    """
    if not classification or not isinstance(classification, dict):
        return _REMEDIATIONS["unknown"]

    category = classification.get("category", "unknown")
    return list(_REMEDIATIONS.get(category, _REMEDIATIONS["unknown"]))


def is_permanent(classification: dict) -> bool:
    """Return *True* if no amount of retrying can change the outcome.

    Currently: billing/quota exhaustion. Callers should stop retrying, surface the
    provider, and let a human add credits or reroute.
    Fail-soft: bad input → ``False``.
    """
    if not classification or not isinstance(classification, dict):
        return False
    return classification.get("category", "unknown") in _PERMANENT_CATEGORIES


def is_transient(classification: dict) -> bool:
    """Return *True* if the error is likely transient and worth retrying.

    Transient: timeout, resource, and auth ONLY when the text shows a credential
    actually expired. A flat 403/permission-denied is not retried — it used to be, and
    that is how a provider's "you are out of credits" answer cost four backoff sleeps
    per task, on every task, indefinitely.

    Fail-soft: bad input → ``False`` (don't retry what we don't understand).
    """
    if not classification or not isinstance(classification, dict):
        return False

    category = classification.get("category", "unknown")
    confidence = classification.get("confidence", 0.0)

    # Permanent beats everything, including a high-confidence match.
    if is_permanent(classification):
        return False

    if category == "auth":
        # Requires positive evidence of expiry. `pattern` is what classify_error
        # matched; fall back to any text the caller kept on the dict.
        evidence = f"{classification.get('pattern', '')} {classification.get('text', '')}"
        return bool(_RETRYABLE_AUTH.search(evidence))

    if category in _TRANSIENT_CATEGORIES and confidence >= HIGH_CONFIDENCE_THRESHOLD:
        return True
    # Low-confidence timeout is still worth one retry
    if category == "timeout":
        return True
    return False


def extract_error_context(error_text: str, max_lines=None) -> dict:
    """Extract structured context from *error_text*.

    Returns ``{"file": Optional[str], "line": Optional[int], "module": Optional[str],
    "snippet": str}``.
    """
    if max_lines is None:
        max_lines = MAX_CONTEXT_LINES

    if not error_text or not isinstance(error_text, str):
        return {"file": None, "line": None, "module": None, "snippet": ""}

    lines = error_text.strip().splitlines()
    snippet_lines = lines[-max_lines:] if len(lines) > max_lines else lines
    snippet = "\n".join(snippet_lines)

    # Try to extract file + line from Python traceback
    file_match = re.search(r'File "([^"]+)", line (\d+)', error_text)
    file_path = file_match.group(1) if file_match else None
    line_no = int(file_match.group(2)) if file_match else None

    # Try to extract module from ModuleNotFoundError
    module_match = re.search(r"No module named ['\"]([^'\"]+)['\"]", error_text)
    if not module_match:
        module_match = re.search(r"ModuleNotFoundError:\s*No module named\s+'?(\S+)'?", error_text)
    module = module_match.group(1) if module_match else None

    return {
        "file": file_path,
        "line": line_no,
        "module": module,
        "snippet": snippet,
    }


def prioritize_errors(errors: list[dict]) -> list[dict]:
    """Sort *errors* by severity (most severe first).

    Each item should be a classification dict (as returned by
    :func:`classify_error`).  Unknown / malformed items sink to the end.
    """
    if not errors or not isinstance(errors, list):
        return []

    def _sort_key(item):
        if not isinstance(item, dict):
            return (len(_SEVERITY_ORDER), 0.0)
        cat = item.get("category", "unknown")
        try:
            sev_idx = _SEVERITY_ORDER.index(cat)
        except ValueError:
            sev_idx = len(_SEVERITY_ORDER)
        # Within same severity, higher confidence first
        conf = item.get("confidence", 0.0)
        return (sev_idx, -conf)

    return sorted(errors, key=_sort_key)
