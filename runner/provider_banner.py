#!/usr/bin/env python3
"""
provider_banner.py — one place that knows what a provider's error banner looks like.

WHY THIS EXISTS
---------------
When a model provider rate-limits or exhausts an account it does not raise; it
returns prose. "You've hit your weekly limit · resets Jul 29 at 5am
(America/Chicago)" arrives through the same channel as a real completion, so
any caller that does not check treats a billing notice as content.

That has already happened twice, in two different pipelines:

  * 2026-07-08: learn_from_merges appended a usage-limit banner straight into
    CLAUDE.md and regression memory, polluting the cached context prefix that
    every future task pays for.
  * A spec-reconcile task was filed whose entire "drift found:" evidence was
    the same banner text. The reconciliation had nothing to reconcile.

Each fix was written where it was needed, so the vocabulary now lives in three
places that have already drifted apart:

  runner.py            RATE / EXHAUST substring tuples
  root_cause.py        PATTERNS["rate_limit"] regex
  learn_from_merges.py _FAILURE_PATTERNS regex list

runner.py knows "5-hour limit" and "raise it at claude.ai"; root_cause.py does
not, so an exhaustion note runner.py handled correctly is classified "unknown"
by the analyzer reading the same string. This module is the union, and those
three import from it. A new banner phrase is now a one-line change in one file.

CONTRACT: nothing here raises, and nothing here needs network or config. These
functions run on the error path, where a second failure is the expensive kind.
"""
import re

# Transient: the provider is throttling but the account still has budget.
# Callers back off or fail over to another vendor.
RATE_SIGNALS = (
    "temporarily limiting", "rate limit", "rate-limited", "ratelimit",
    "429", "overloaded", "too many requests", "slow down",
)

# Terminal for this window: the account is out of budget. Backing off does not
# help — the caller must switch accounts or wait for the stated reset.
EXHAUST_SIGNALS = (
    "usage limit", "out of credits", "insufficient_quota", "quota",
    "weekly limit", "hit your weekly", "limit · resets", "limit - resets",
    "reached your usage", "usage limit reached", "upgrade to increase",
    "5-hour limit", "hour limit reached", "session limit",
    "limit reached ∙ resets", "spend limit", "monthly spend", "monthly limit",
    "hit your monthly", "limit · raise it", "raise it at claude.ai",
    "credit balance is too low",
)

def _rx(extra_shapes, signals):
    """Compile a regex covering hand-written shapes OR any known signal phrase.

    Built FROM the substring lists rather than written alongside them. Keeping
    two hand-maintained copies in one file would reproduce, at smaller scale,
    exactly the drift this module exists to end: a caller scanning free text
    would answer differently from a caller matching a phrase.
    """
    parts = list(extra_shapes) + [re.escape(s) for s in signals]
    return re.compile("|".join(parts), re.I)


# Shapes the substring lists cannot express, unioned with the lists themselves,
# so free-text scanning and phrase matching always agree.
RATE_LIMIT_RX = _rx((r"rate.limit", r"\b429\b", r"quota\s+(?:exceeded|reached)"),
                    RATE_SIGNALS)

EXHAUSTED_RX = _rx((
    r"\b(?:weekly|daily|monthly|usage|session|spend)\s+limit\b",
    r"\bhit your (?:weekly|monthly|daily)\b",
    r"\b\d+[\s-]hour limit\b",                   # "5-hour limit reached"
    r"\blimit\s*[·∙-]\s*(?:resets|raise it)\b",
    r"\bresets?\s+\S+",                          # "resets Jul 8 at 6am", "resets 3pm"
), EXHAUST_SIGNALS)

# A transport/server error that also arrives as prose rather than an exception.
PROVIDER_ERROR_RX = re.compile(
    r"\bHTTP\s+(?:Error\s+)?[45]\d\d\b"
    r"|\b(?:Internal Server Error|Not Found|Bad Gateway|Service Unavailable"
    r"|Too Many Requests|Gateway Timeout)\b", re.I)

# Ordered most-specific first: an exhaustion banner usually also contains
# rate-limit vocabulary, and "out of budget" is the more actionable answer.
_ORDERED = (
    ("exhausted", EXHAUSTED_RX, EXHAUST_SIGNALS),
    ("rate_limited", RATE_LIMIT_RX, RATE_SIGNALS),
    ("provider_error", PROVIDER_ERROR_RX, ()),
)

# For callers that want to iterate the regexes (e.g. a content quality gate).
PATTERNS = (EXHAUSTED_RX, RATE_LIMIT_RX, PROVIDER_ERROR_RX)


def classify(text):
    """Return 'exhausted', 'rate_limited', 'provider_error', or None.

    None means "this does not look like a provider banner" — it is not a claim
    that the text is good, only that this module has no opinion about it.
    """
    low = _low(text)
    if not low:
        return None
    for name, rx, signals in _ORDERED:
        if any(s in low for s in signals) or rx.search(low):
            return name
    return None


def is_banner(text):
    """True if the text looks like a provider banner rather than real output."""
    return classify(text) is not None


def reason(text):
    """A short, loggable explanation, or None if this is not a banner.

    Returns the matched phrase rather than the pattern that matched it: a log
    line saying `provider banner (exhausted): "hit your weekly"` is something
    an operator can act on, where a regex source is not.
    """
    low = _low(text)
    if not low:
        return None
    for name, rx, signals in _ORDERED:
        for signal in signals:
            if signal in low:
                return '%s: "%s"' % (name, signal)
        found = rx.search(low)
        if found:
            return '%s: "%s"' % (name, found.group(0).strip())
    return None


def _low(text):
    """Lowercased text, or '' for anything unusable. Never raises."""
    try:
        if not text or not isinstance(text, str):
            return ""
        return text[:20000].lower()
    except Exception:
        return ""
