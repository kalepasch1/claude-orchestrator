"""Keep the part of a git/build stderr that says WHY, not just the last 160 bytes.

WHY THIS EXISTS
---------------
The fleet stored `stderr[-160:]` in `releases.note`, in the `[branch-share] push ... failed`
log line, and in a dozen other places. Git prints the actionable line FIRST and a multi-line
hint block AFTER it:

    ! [rejected]        main -> main (fetch first)
    error: failed to push some refs to 'https://github.com/...'
    hint: Updates were rejected because the remote contains work that you do
    hint: not have locally. ... integrate the remote changes, use 'git pull'

A 160-byte tail therefore captures the *hint* and discards the *cause* -- reliably, every
time. 4,080 failed releases were recorded that way. On 2026-08-16 two separate investigations
of those records reached the wrong root cause: a grep for "rejected" across the whole log
returned zero matches while 374 rejections were actually present, because the word had been
truncated away at write time.

`digest()` keeps the diagnostic lines regardless of where they appear, then spends whatever
budget remains on the tail. It never raises: diagnostics must not be able to break a caller.
"""

import re

#: Lines that carry the cause. Ordered by how much they usually explain.
_MARKERS = (
    re.compile(r"^\s*!\s*\["),                       # ! [rejected] / ! [remote rejected]
    re.compile(r"^\s*(fatal|error):", re.I),
    re.compile(r"\b(rejected|denied|forbidden|unauthorized|not\s+permitted)\b", re.I),
    re.compile(r"\b(command not found|no such file|permission denied)\b", re.I),
    re.compile(r"\b(could not resolve host|connection refused|timed out)\b", re.I),
    re.compile(r"\b(non-fast-forward|would clobber|unrelated histories)\b", re.I),
    re.compile(r"^\s*remote:\s*\S", re.I),
)
#: Pure noise: git's own advice, repeated verbatim on every failure.
_NOISE = re.compile(r"^\s*(hint|warning: redirecting|Everything up-to-date)\b", re.I)

DEFAULT_LIMIT = 800


def _lines(text):
    try:
        return [ln.rstrip() for ln in str(text or "").splitlines() if ln.strip()]
    except Exception:
        return []


def diagnostic_lines(text):
    """Just the cause-bearing lines, in source order, deduplicated. Never raises."""
    out, seen = [], set()
    for ln in _lines(text):
        if _NOISE.match(ln):
            continue
        for marker in _MARKERS:
            try:
                if marker.search(ln):
                    key = ln.strip()
                    if key not in seen:
                        seen.add(key)
                        out.append(key)
                    break
            except Exception:
                continue
    return out


def digest(text, limit=DEFAULT_LIMIT):
    """A bounded summary of `text` that preserves the cause. Never raises.

    Diagnostic lines come first and are never dropped while budget remains. Any leftover
    budget is spent on the tail, so context that only appears at the end still survives.
    Returns "" for empty input, so callers can keep using `or` fallbacks.
    """
    try:
        raw = str(text or "").strip()
        if not raw:
            return ""
        limit = max(1, int(limit or DEFAULT_LIMIT))
        if len(raw) <= limit:
            return raw

        found = diagnostic_lines(raw)
        head = ""
        for ln in found:
            candidate = (head + "\n" + ln) if head else ln
            if len(candidate) > limit:
                break
            head = candidate

        remaining = limit - len(head) - 5   # room for the elision marker
        if remaining <= 0:
            return head[:limit]

        tail = _tail_at_a_boundary(raw, remaining)
        if head and tail.strip() and tail.strip() not in head:
            return f"{head}\n...\n{tail}"
        return head or _tail_at_a_boundary(raw, limit)
    except Exception:
        # A diagnostic helper must never be the reason a caller fails.
        try:
            return str(text or "")[-DEFAULT_LIMIT:]
        except Exception:
            return ""


def _tail_at_a_boundary(raw, budget):
    """The last `budget` characters, starting at a line or word boundary.

    THE HELPER THAT EXISTS TO STOP TAIL-TRUNCATION WAS TAIL-TRUNCATING. Every caller
    in the fleet was migrated to digest() so that `stderr[-160:]` would stop cutting
    the cause off the front -- and digest() ended with `raw[-remaining:]`, a bare
    slice, so it cut mid-word anyway. Four live rows, all read by a human or by an
    automated repair task:

        [gate:build] ... self-heal queued: nthropic-ai/sdk' imported from ...
        [gate:qa]    ... self-heal queued: e found in file /Users/.../check-patch-source.test.mjs
        [gate:qa]    ... self-heal queued:  duration_ms 30315.778334 ...

    The first is missing both "Cannot find package" and the "@a" of the package name.
    The second is missing "No test suit". A reader cannot tell from any of them what
    actually went wrong, which is the entire failure this module was written to end.

    Prefer a newline, then a space. Only cut inside a token when a single token is
    longer than the whole budget -- a 300-character minified stack frame, say -- and
    mark it with a leading ellipsis so the reader knows the front is missing rather
    than guessing at a word that starts "nthropic".
    """
    raw = str(raw or "")
    budget = max(1, int(budget))
    if len(raw) <= budget:
        return raw
    window = raw[-budget:]
    newline = window.find("\n")
    if 0 <= newline < budget - 1:
        return window[newline + 1:].lstrip("\r")
    space = window.find(" ")
    if 0 <= space < budget - 1:
        return window[space + 1:]
    return "…" + window[1:]
