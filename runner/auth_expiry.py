"""One vocabulary for "the credentials expired", shared by everything that asks.

The problem this solves
-----------------------
Three modules independently decide whether a failure was an expired credential,
and they disagreed. Measured against the strings this fleet actually emits:

    message                                        infra_recovery  stuck_reaper  host_update
    Failed to authenticate: OAuth session expired…       yes           yes         no
    OAuth token has expired. Please run /login           yes           NO          yes
    Please run /login                                    NO            NO          yes
    invalid api key                                      NO            NO          yes
    authentication_error                                 NO            NO          yes
    Refresh token is invalid                             NO            NO          NO

Every NO in the first column is a task whose work is thrown away.
`blocked_triage.infra_failure_recovery` exists precisely to requeue tasks that
burned their attempts on platform failure rather than bad code — an audit found
48 such tasks — and it was missing most of the ways this platform says "log in
again". Every NO in the second column is a RUNNING task stuck on dead
credentials that `stuck_reaper` diagnoses as `unknown` instead of `auth_expired`,
so it waits out the stale timeout instead of being reset immediately.

The failure mode is quiet in both directions, which is why it survived: nothing
errors, the task simply stays quarantined or stuck, and the credential is
re-authenticated hours later by a human who never learns what it cost.

Why one module
--------------
Three regexes over the same vocabulary drift the moment a provider changes its
wording — which is how they got here. A caller that needs an auth check now asks
this module; a new provider phrasing is added in one place and every caller
improves at once.

What is deliberately NOT here
-----------------------------
Billing and quota failures ("credit balance is too low", "usage limit reached",
rate limits, 429). They are also infrastructure and also worth recovering, but
they are not expired credentials: re-authenticating does not fix them, and the
operator action is different. `blocked_triage` keeps its own broader
infrastructure vocabulary for that and composes it with this one.
"""

from __future__ import annotations

import re

# Each entry is a phrasing this fleet has actually seen, or the documented
# wording of a provider it talks to. Kept as one alternation so callers get
# identical behaviour rather than approximately-identical behaviour.
#
# Ordering is irrelevant (any match wins); grouping is by source so an addition
# lands next to its siblings.
_PATTERNS = (
    # Claude Code / Anthropic OAuth
    r"oauth",
    r"session expired",
    r"could not be refreshed",
    r"refresh token",
    r"token (has )?expired",
    r"expired token",
    r"please run /login",
    r"run /login",
    r"not logged in",
    r"login required",
    r"authentication_error",
    r"authentication failed",
    r"failed to authenticate",
    # Separators vary by provider: "invalid api key", "invalid_api_key",
    # "invalid-api-key" are all the same failure and all appear in the wild.
    r"invalid[ _-]?api[ _-]?key",
    r"missing[ _-]?api[ _-]?key",
    # "credentials could not be read" truncates to "credentials could not be" in
    # some log tails, so the trailing verb must not be required.
    r"credentials? (could not be|are invalid|are expired|are absent|are missing"
    r"|invalid|expired|absent|missing)",
    r"credential.*invalid",
    r"not authenticated",
    r"unauthenti?cated",
    # HTTP shapes
    r"unauthorized",
    r"forbidden",
    r"\b401\b",
    r"\b403\b",
    # git credential helper
    r"could not read username",
    r"could not read password",
    r"terminal prompts disabled",
    r"authentication is required",
    # generic
    r"auth\.?\s?fail",
    r"auth\.?\s?error",
    r"re-?authenticate",
)

AUTH_EXPIRY_RE = re.compile("|".join(_PATTERNS), re.I)

# What an operator has to do about it. Every caller that reports an auth failure
# should say the same thing, because they are all describing one host-level
# action that only a human at that keyboard can take.
REMEDIATION = ("Re-authenticate on this host (Claude Code: /login; "
               "git: refresh the credential helper).")


def is_auth_expiry(text) -> bool:
    """True when `text` is evidence that a credential expired or is absent.

    Fail-soft by design: a non-string, None, or unreadable value returns False
    rather than raising. This is called from triage and reaper paths that must
    never crash on a malformed log tail — but note the direction. False here
    means "no evidence of auth failure", which for a caller like
    `infra_failure_recovery` means the task is NOT recovered. That is the
    conservative answer: leaving a task quarantined is recoverable by a human,
    while requeueing a genuinely broken task burns more attempts.
    """
    try:
        return bool(AUTH_EXPIRY_RE.search(text or ""))
    except TypeError:
        return False


def auth_expiry_evidence(text, limit: int = 60) -> str:
    """The matched phrase, for a digest that names WHY rather than asserting it.

    Returns "" when there is no match. Truncated because this goes into notes
    and alert payloads that are read by a human scanning a list.
    """
    try:
        m = AUTH_EXPIRY_RE.search(text or "")
    except TypeError:
        return ""
    return m.group(0)[:limit] if m else ""
