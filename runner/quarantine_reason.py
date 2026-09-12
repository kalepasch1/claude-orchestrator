#!/usr/bin/env python3
"""quarantine_reason.py — a machine-readable reason on every quarantine event.

WHY THIS EXISTS
---------------
Quarantined items sit indefinitely or require manual investigation, and the
reason is structural: nothing writes down *why* in a form a machine can read.

`blocker_quarantine` writes prose — "blocker-quarantine: quarantined as
buildfail; replacement queued as X. Original blocker: ..." — and
`quarantine_breakdown` recovers the category by regexing that prose back out
(`quarantined as (?P<category>[a-z-]+);`). That only works for notes this one
module wrote. More than twenty other modules park tasks as QUARANTINED with
free-text notes of their own:

    "repair-ceiling: orphaned-running after 9 repairs without reaching a
     completed state. attempt=1. Repair is not converging; parked for review"

Nothing can be counted, routed or auto-remedied from that. It is a sentence for
a human who is not reading it.

REASON IS NOT CATEGORY
----------------------
`blocker_quarantine.classify()` answers "what kind of failure is this" —
buildfail, testfail, conflict, rework. That is the right question for choosing a
replacement task, and this module does not replace it.

A reason answers a narrower question: *what specific thing would unstick this*.
"conflict" does not tell you whether to rebase or to regenerate a fixture;
`merge_conflict` and `fixture_stale` do. The taxonomy below is closed and each
member maps to exactly one remedy, because a reason nobody can act on is the
prose problem again with better punctuation.

THE TAG
-------
`tag()` appends `[quarantine-reason:<reason>]` to the note. It is idempotent, it
survives the note truncation every writer applies (it goes last and is short),
and `parse()` reads it back. Readers prefer the tag and fall back to the legacy
prose regex, so notes written before this module still count.
"""

from __future__ import annotations

import re

# ── The taxonomy ─────────────────────────────────────────────────────────────
# Closed set. Ordered: the first match wins, so the more specific reasons come
# before the ones whose patterns are broad enough to swallow them.

MERGE_CONFLICT = "merge_conflict"
TEST_TIMEOUT = "test_timeout"
MISSING_DEPENDENCY = "missing_dependency"
PRE_MERGE_GATE_FAIL = "pre_merge_gate_fail"
FIXTURE_STALE = "fixture_stale"
MISSING_BRANCH = "missing_branch"
REPAIR_CEILING = "repair_ceiling"
INFRA = "infra"

# ── Administrative parks ─────────────────────────────────────────────────────
# Not failures. Run against beethoven's 575 live QUARANTINED rows, the first
# version of this module returned `unknown` for 91.3% of them — and the notes
# showed why: the bulk of quarantine is HOUSEKEEPING, not breakage.
# integration_sweeper (196), GC (173), recovery_dedup (56), spec-lost (36),
# queue-bankruptcy (21), semantic-dedupe (20). Calling those "unknown — read the
# note by hand" tells a human to investigate 445 items that need no
# investigation, which is a worse instruction than silence.
DUPLICATE = "duplicate"
SWEPT_STALE = "swept_stale"
SPEC_LOST = "spec_lost"
DEGENERATE_PROMPT = "degenerate_prompt"
QUEUE_BANKRUPTCY = "queue_bankruptcy"

UNKNOWN = "unknown"

#: reason -> the one action that would unstick it.
REMEDIES = {
    MERGE_CONFLICT: "rebase the task branch on the current base and re-run the train",
    TEST_TIMEOUT: "re-run with a raised timeout budget; do not rework the source",
    MISSING_DEPENDENCY: "repair the repo setup / install path, then re-run",
    PRE_MERGE_GATE_FAIL: "fix the gate finding the pre-merge check reported, not the test",
    FIXTURE_STALE: "regenerate the fixture or snapshot, then re-run",
    MISSING_BRANCH: "reconstruct the smallest equivalent patch and push the branch",
    REPAIR_CEILING: "stop repairing; the loop is not converging and needs a human read",
    INFRA: "retry after the host recovers; nothing in the diff is at fault",
    DUPLICATE: "none — the surviving task carries the work; close, do not investigate",
    SWEPT_STALE: "none — parked by housekeeping; reopen only if the work is still wanted",
    SPEC_LOST: "the specification is gone from this row; re-specify from source or close",
    DEGENERATE_PROMPT: "nothing to implement; re-specify the task in English or close",
    QUEUE_BANKRUPTCY: "already settled elsewhere; close, do not re-queue without an owner",
    UNKNOWN: "read the note by hand — no reason could be established",
}

#: (reason, pattern). First match wins, so order is the classification policy.
_RULES = [
    # ── Administrative parks come first ──────────────────────────────────────
    # These are self-declarations written by the module that did the parking, so
    # they are stronger evidence than any keyword found in a log tail. A note
    # that says "recovery_dedup: superseded by a newer recovery task" is not
    # ambiguous about why the row is parked.
    #
    # DUPLICATE precedes SWEPT_STALE deliberately: the commonest GC note is
    # "GC: semantic-dedupe: 0.992 duplicate of <slug>" — it opens with the
    # sweeper's prefix but the actual reason is the duplication.
    (DUPLICATE, re.compile(
        r"recovery_dedup|semantic[- ]dedupe|"
        r"\bduplicate of\b|duplicate queued slug|"
        r"superseded by a newer",
        re.I)),
    (DEGENERATE_PROMPT, re.compile(
        r"PATCH TEMPLATE (?:or garbage|stub)|"
        r"(?:hex[- ]only|degenerate|binary) PATCH TEMPLATE|"
        r"garbage prompt|"
        r"no readable implementation intent",
        re.I)),
    (SPEC_LOST, re.compile(
        r"\bspec-lost\b|"
        r"specification is not recoverable|"
        r"prompt was overwritten with the",
        re.I)),
    (QUEUE_BANKRUPTCY, re.compile(
        r"queue[- ]bankruptcy|"
        r"original task .{0,120} is already DONE/MERGED",
        re.I)),
    (SWEPT_STALE, re.compile(
        r"integration_sweeper|"
        r"\bGC:|branch gc|"
        r"closed to stop phantom|"
        r"recovery exhausted",
        re.I)),
    # Stale fixtures/snapshots first: their text almost always ALSO mentions a
    # failing test, so a test-shaped rule placed earlier would absorb them and
    # send "rework the source" where "regenerate the fixture" was needed.
    (FIXTURE_STALE, re.compile(
        r"snapshot (?:test )?(?:failed|mismatch|obsolete|outdated)|"
        r"obsolete snapshot|snapshots? (?:do not|don't) match|"
        r"fixture (?:is )?(?:stale|outdated|mismatch|out of date)|"
        r"golden file (?:mismatch|differs)|"
        r"toMatchSnapshot|"
        r"run .{0,20}(?:--update-snapshots|-u\b|:update)",
        re.I)),
    # Missing dependency before build/test: a missing module fails the build,
    # and reworking the source for it is the wrong repair.
    (MISSING_DEPENDENCY, re.compile(
        r"ModuleNotFoundError|ERR_MODULE_NOT_FOUND|"
        r"cannot find module|module not found|"
        r"ImportError|"
        r"command not found|"
        r"no such file or directory.*node_modules|"
        r"package .{0,40} is not installed|"
        r"could not resolve (?:dependency|import)|"
        r"unmet peer dependency|"
        r"vitest.*not found|missing dependenc",
        re.I)),
    (MERGE_CONFLICT, re.compile(
        r"merge conflict|CONFLICT \(|"
        r"needs manual rebase|"
        r"automatic merge failed|"
        r"conflicting files|"
        r"still conflicts after|"
        r"(?:base )?won't fast[- ]forward|cannot fast[- ]forward|"
        r"<<<<<<<|"
        r"could not apply .{0,60}(?:conflict)?",
        re.I)),
    (PRE_MERGE_GATE_FAIL, re.compile(
        r"pre[- ]merge gate|merge[- ]train.{0,30}gate|"
        r"regression guard|regressfail|"
        r"disclosure (?:qa )?gate|public[- ]copy (?:disclosure )?gate|"
        r"gate is RED|gate blocked|blocked by gate|"
        r"convention[- ]lint (?:gate|regression)|"
        r"ratchet (?:violation|regression)",
        re.I)),
    (TEST_TIMEOUT, re.compile(
        r"test.{0,30}time(?:d )?out|time(?:d )?out.{0,30}test|"
        r"ETIMEDOUT|"
        r"exceeded timeout of|"
        r"hook timed out|"
        r"test (?:suite )?(?:exceeded|hung|never finished)|"
        r"error_max_turns",
        re.I)),
    (MISSING_BRANCH, re.compile(
        r"missing[- ]branch|branch (?:is )?missing|"
        r"no agent branch|branch not found on origin|"
        r"unknown revision or path not in the working tree",
        re.I)),
    (REPAIR_CEILING, re.compile(
        r"repair[- ]ceiling|"
        r"repair is not converging|"
        r"after \d+ repairs|"
        r"orphaned[- ]running after|"
        r"stuck[- ]reaper|after \d+ stuck cycles|death_loop",
        re.I)),
    (INFRA, re.compile(
        r"out of memory|\bOOM\b|\boom[-_ ]?kill(?:ed|er)?\b|"
        r"no space left on device|ENOSPC|disk full|"
        r"ECONNRESET|ECONNREFUSED|socket hang up|connection reset|"
        r"network (?:error|unreachable|timeout)|DNS resolution failed|"
        r"cannot allocate memory|worker process exited|"
        r"runner (?:crash|died)|fatal: unable to access|"
        r"worktree.{0,20}locked|cannot create worktree",
        re.I)),
]

REASONS = tuple(r for r, _ in _RULES) + (UNKNOWN,)

_TAG_RE = re.compile(r"\[quarantine-reason:([a-z_]+)\]")
#: The prose that blocker_quarantine has always written. Kept so notes predating
#: the tag still classify, rather than all reading as `unknown` on day one.
_LEGACY_CATEGORY_RE = re.compile(r"quarantined as (?P<category>[a-z-]+)\s*;", re.I)

#: blocker_quarantine's coarse categories -> the nearest reason. Only used when
#: no tag is present and no pattern matched; a category is weaker evidence than
#: the failure text, so it is consulted last.
_LEGACY_CATEGORY_TO_REASON = {
    "conflict": MERGE_CONFLICT,
    "missing-branch": MISSING_BRANCH,
    "flake": INFRA,
    "regressfail": PRE_MERGE_GATE_FAIL,
}


def classify(*texts) -> str:
    """Return the reason for a quarantine, from the note / log / whatever else.

    Accepts several strings so callers can pass note, log_tail and category
    without concatenating first. Never raises; returns UNKNOWN when nothing
    matches, because a wrong confident answer costs more than an honest gap.
    """
    blob = "\n".join(str(t or "") for t in texts)
    if not blob.strip():
        return UNKNOWN

    tagged = parse(blob)
    if tagged:
        return tagged

    for reason, pattern in _RULES:
        if pattern.search(blob):
            return reason

    m = _LEGACY_CATEGORY_RE.search(blob)
    if m:
        mapped = _LEGACY_CATEGORY_TO_REASON.get(m.group("category").lower())
        if mapped:
            return mapped

    return UNKNOWN


def parse(note) -> "str | None":
    """Read the reason back out of a tagged note, or None if it carries no tag."""
    m = _TAG_RE.search(str(note or ""))
    if not m:
        return None
    reason = m.group(1)
    return reason if reason in REASONS else None


def tag(note, reason) -> str:
    """Append `[quarantine-reason:<reason>]` to `note`. Idempotent.

    Re-tagging a note replaces the existing tag rather than appending a second
    one; two tags on one note is exactly the ambiguity the tag exists to remove.
    An unrecognised reason is stored as UNKNOWN rather than widening the closed
    set through a typo.
    """
    text = str(note or "").rstrip()
    reason = reason if reason in REASONS else UNKNOWN
    text = _TAG_RE.sub("", text).rstrip()
    marker = "[quarantine-reason:%s]" % reason
    return (text + " " + marker).strip() if text else marker


def annotate(note, *texts) -> str:
    """classify() the evidence and tag() the note with the result, in one call.

    This is what a writer parking a task should call. `note` is included in the
    evidence: the note usually IS the failure description.
    """
    return tag(note, classify(note, *texts))


def remedy_for(reason) -> str:
    """The one action that would unstick a task parked for this reason."""
    return REMEDIES.get(reason, REMEDIES[UNKNOWN])
