"""Pick the part of a gate's output that says what FAILED.

THE PROBLEM THIS EXISTS FOR
---------------------------
_run_tests returns up to 12,000 characters -- the last 6,000 of stdout plus the last
6,000 of stderr -- and every consumer took the FRONT of it:

    _task_patch(task, {"state": "TESTFAIL",
                       "note": f"... tests failed on rebased {branch}: {tail[:200]}"})
    _log(pname, slug, "TESTFAIL", (_gl + " " + tail).strip()[:160])
    _pm.record(..., gate_reason=tail[:200])

Test runners print the failure summary at the END. Taking the first 200 characters of a
window that begins mid-listing yields an arbitrary slice of whatever happened to be
running -- usually passing tests, or the middle of a type declaration.

Measured 2026-09-02 across 385 TESTFAIL records in one merge-train log:

    carrying no failure marker of any kind        290   (75%)
    ...of those, beginning with PASSING output     61

What a repair agent was actually handed as the evidence for a failure:

    [smarter]    "ByName: string; workspaceId: string; createdAt: string; lastActi"
    [beethoven]  "capability across products (0.610084ms"
    [tomorrow]   "ests__/tracing.test.ts > tracing.withSpan > clears currentSpan af"

That is the input to agentic_repair's prompt. A repair that begins from a fragment of a
passing test cannot be expected to fix anything, and the fleet then spends a full agent
run on it -- and, at the repair ceiling, quarantines the task.

WHAT THIS DOES
--------------
Prefer lines that carry a failure marker; failing that, take the TAIL rather than the
head, because that is where runners put their summaries. Always cut on line boundaries so
the excerpt never begins mid-word.

Deliberately NOT a parser for any particular runner. vitest, jest, pytest, tsc, vue-tsc,
npm and bash all appear in this fleet, and a shape-specific parser is one toolchain change
away from silently returning nothing. Markers are matched case-insensitively and the
fallback is always something rather than "".
"""
import re

#: Lines worth showing a human or an agent, in rough order of how specific they are.
#: Kept broad on purpose: a false positive costs a line of noise, a false negative costs
#: the whole diagnosis.
_MARKERS = re.compile(
    r"(?i)("
    r"\bFAIL\b|\bFAILED\b|\bfailing\b|\bfailure\b"
    r"|^\s*[✗×✖]|\bAssertionError\b|\bTraceback\b|\bException\b"
    r"|\bError\b|\berror TS\d+|\bexpected\b|\breceived\b"
    r"|cannot find|not found|unresolved|could not resolve|failed to resolve"
    r"|timed out|timeout|command not found|refus|denied|EACCES|ENOENT"
    r"|\bTests?\s+\d+\s+failed|\d+\s+failing|\bexit code\b"
    r")")

#: A line that is only a passing result carries no diagnosis, and matching "error" inside
#: a passing test's NAME would otherwise pull it in.
_PASSING = re.compile(r"^\s*[✓√]|^\s*ok\s+\d|^\s*PASS\b")


#: An aggregate count is a fact, not a diagnosis. Measured on the first live records this
#: produced (2026-09-02, tomorrow): the excerpt read
#:     "Test Files  3 failed | 697 passed | 1 skipped (701) | Tests  3 failed | 12911 passed"
#: which tells a repair agent that three of 12,925 tests failed and nothing about WHICH.
#: The named lines -- the failing file, the failing test, the assertion -- are worth more
#: per character, so they are selected first and the aggregate only fills what is left.
_AGGREGATE = re.compile(
    r"(?i)^\s*(test files|tests|snapshots|suites)\s+\d|\b\d+\s+(passed|skipped|todo)\b")

#: Lines that name the thing that broke: a failing spec, a test id, a file:line, an
#: assertion, a missing module.
_SPECIFIC = re.compile(
    r"(^\s*[✗×✖❯]|\bFAIL\b|\bFAILED\b|AssertionError|Traceback"
    r"|\berror TS\d+|[\w./-]+\.(ts|tsx|js|jsx|mjs|vue|py):\d+"
    r"|Cannot find|not found|could not resolve|command not found|ENOENT)")


def failure_lines(output):
    """Lines of `output` that report a failure, most specific first.

    Ordering, not filtering: everything a marker matched is still returned, so a runner
    whose only output is an aggregate still yields something.
    """
    specific, aggregate = [], []
    for line in (output or "").splitlines():
        if not line.strip():
            continue
        if _PASSING.match(line):
            continue
        if not _MARKERS.search(line):
            continue
        line = line.rstrip()
        if _SPECIFIC.search(line):
            specific.append(line)
        elif _AGGREGATE.search(line):
            aggregate.append(line)
        else:
            specific.append(line)
    return specific + aggregate


def excerpt(output, limit=240):
    """Up to `limit` characters of `output` that actually describe the failure.

    Falls back to the TAIL of the output, on line boundaries, when nothing matches --
    never to the head, and never to "".
    """
    text = (output or "").strip()
    if not text:
        return ""
    if limit <= 0:
        return ""

    hits = failure_lines(text)
    if hits:
        picked, size = [], 0
        for line in hits:
            if size + len(line) + 1 > limit and picked:
                break
            picked.append(line)
            size += len(line) + 1
        joined = " | ".join(picked).strip()
        if joined:
            return joined[:limit]

    # Nothing matched: the last lines beat the first ones for every runner in this fleet.
    lines, tail, size = text.splitlines(), [], 0
    for line in reversed(lines):
        line = line.rstrip()
        if not line.strip():
            continue
        if size + len(line) + 1 > limit and tail:
            break
        tail.insert(0, line)
        size += len(line) + 1
    if tail:
        return (" | ".join(tail))[-limit:]
    return text[-limit:]
