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

        tail = raw[-remaining:]
        if head and tail.strip() and tail.strip() not in head:
            return f"{head}\n...\n{tail}"
        return head or raw[-limit:]
    except Exception:
        # A diagnostic helper must never be the reason a caller fails.
        try:
            return str(text or "")[-DEFAULT_LIMIT:]
        except Exception:
            return ""
