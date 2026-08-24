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
    # 2026-08-24: the fleet produced empty commits for weeks because none of
    # these matched. Google, OpenAI and DeepSeek each say "you are out of
    # money" in their own words, and each ships it as a 429/402 — so without
    # this vocabulary the banner read as a TRANSIENT rate limit, the provider
    # was never demoted, and every routed task burned aider's 60s retry loop
    # against a wall that only a payment can move.
    "credits are depleted", "credits depleted", "prepayment credits",
    "no credits remaining", "credits remaining", "credit_balance_exhausted",
    "used all available credits", "insufficient balance", "add credits",
    "payment required", "purchase more credits",
    # Deliberately NOT here: the bare word "billing". These patterns are also
    # used as a content-quality gate (learn_from_merges rejects any
    # distillation that matches one), so a signal must be specific enough that
    # ordinary product work cannot trip it. A merged task summarised as "add
    # billing page" is real work, not a provider banner.
)

# Terminal, and fixable by NEITHER waiting nor paying: the model id itself is
# gone. Providers retire ids on their own schedule, and a config that still
# names one fails 404 forever. That is a config bug, not a capacity problem —
# it must never be retried, and it must not be reported as exhaustion, because
# "top up your account" sends the operator to fix the wrong thing.
MODEL_GONE_SIGNALS = (
    "is no longer available", "no longer available to new users",
    "is not found for api version", "model_not_found",
    "does not exist or you do not have access",
    "has been deprecated", "model has been retired",
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

MODEL_GONE_RX = _rx((r"\bmodels?/[\w.\-]+ is (?:no longer available|not found)\b",),
                    MODEL_GONE_SIGNALS)

# A transport/server error that also arrives as prose rather than an exception.
PROVIDER_ERROR_RX = re.compile(
    r"\bHTTP\s+(?:Error\s+)?[45]\d\d\b"
    r"|\b(?:Internal Server Error|Not Found|Bad Gateway|Service Unavailable"
    r"|Too Many Requests|Gateway Timeout)\b", re.I)

# Ordered most-specific first: an exhaustion banner usually also contains
# rate-limit vocabulary, and "out of budget" is the more actionable answer.
# A retired model id sits ahead of both — it also 404s and often mentions
# quota-adjacent words, but no amount of waiting or paying brings the id back.
_ORDERED = (
    ("model_gone", MODEL_GONE_RX, MODEL_GONE_SIGNALS),
    ("exhausted", EXHAUSTED_RX, EXHAUST_SIGNALS),
    ("rate_limited", RATE_LIMIT_RX, RATE_SIGNALS),
    ("provider_error", PROVIDER_ERROR_RX, ()),
)

# For callers that want to iterate the regexes (e.g. a content quality gate).
PATTERNS = (MODEL_GONE_RX, EXHAUSTED_RX, RATE_LIMIT_RX, PROVIDER_ERROR_RX)


def classify(text):
    """Return 'model_gone', 'exhausted', 'rate_limited', 'provider_error', or None.

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


# litellm names its exception classes after the HTTP status it wrapped, so a
# 429 that actually means "your balance is zero" arrives as the string
# "litellm.RateLimitError: ... prepayment credits are depleted ...". Scanning
# that raw let the WRAPPER decide the verdict: "ratelimiterror" contains
# "ratelimit", so the banner classified as transient before anything read the
# message. The message is the provider's evidence; the wrapper is litellm's
# label for the status code. Strip the label, keep the code.
_WRAPPER_RX = re.compile(
    r"\b\w*(?:rate ?limit|notfound|not ?found|apiconnection|api|auth"
    r"|permissiondenied|badrequest|internalserver|serviceunavailable"
    r"|contextwindowexceeded|timeout|unprocessableentity)error\b", re.I)


def _low(text):
    """Lowercased text with exception-class wrappers removed, or '' if unusable.

    Never raises. The status code itself survives — "Error code: 429" is the
    provider speaking and is real evidence; "RateLimitError" is only litellm's
    name for that status and must not outvote the message body.
    """
    try:
        if not text or not isinstance(text, str):
            return ""
        return _WRAPPER_RX.sub(" ", text[:20000]).lower()
    except Exception:
        return ""
