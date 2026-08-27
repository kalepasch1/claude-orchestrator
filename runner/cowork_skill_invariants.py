"""Static checks over the cowork-executor skill files.

WHY THIS EXISTS — the false-success signal, in the one place still carrying it.

`runner/db.py` already distinguishes "queue empty" from "queue deadlocked": it
records `_LAST_CLAIM_DIAGNOSTIC`, exposes `why_no_claim()`, and prints
`[claim] STALLED` when a scan considered rows but claimed none. The cowork
executor skills never got that fix. Their Step 1 still reads:

    If 0 rows -> heartbeat, write `<run-summary>`, stop.

A claim CTE returns zero rows for two completely different reasons — nothing
left to do, or everything left to do is blocked — and the skill maps both to
"work complete". That is how sixteen executors reported clean runs against a
queue that had not moved since 2026-07-15 (see QUEUE-DEADLOCK-2026-08-25.md),
and it recurred on 2026-08-27: 143 QUEUED tasks, zero claimable, every single
dependency edge pointing at a task in a terminal state that can never become
DONE or MERGED.

The remedy is not to widen the dependency gate — that would launch work whose
stated prerequisite never happened, which this repo's CLAUDE.md calls the most
expensive failure the fleet has. The remedy is to make an executor *say which
case it is in*, so a stall is visible instead of being reported as success.

These checks are deliberately textual. The skills are prose-plus-SQL read by a
model, not code that can be imported and unit-tested, so the only thing that can
hold a line here is an assertion that the required wording is present. Every
check is pure: it takes skill text and returns findings, touches no filesystem
and no network.
"""

import re

#: Terminal states a dependency can sit in forever. A queued task blocked by one
#: of these will never become claimable, no matter how many times it is scanned.
#: Kept here so the checker and the docs quote one list.
TERMINAL_DEP_STATES = (
    "DECOMPOSED",
    "QUARANTINED",
    "SUPERSEDED",
    "CLOSED",
    "PHANTOM_UNVERIFIED",
)

#: States that genuinely satisfy a dependency. Mirrors
#: db._DEP_SATISFYING_STATES and the claim_next() RPC.
DEP_SATISFYING_STATES = ("DONE", "MERGED", "DEPLOYED_AND_VERIFIED")


def _norm(text):
    """Lowercase with runs of whitespace collapsed. Never raises.

    Skill files are hand-edited markdown: the same sentence appears with
    different line wrapping across the sixteen copies, so a substring test on
    raw text gives false negatives that look like real regressions.
    """
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def has_claimability_preflight(text):
    """True when the skill checks the QUEUED count before declaring the queue empty.

    This is the invariant the 2026-08-25 diagnosis ranked first: "Make the claim
    step distinguish queued=0 from claimable=0, and alert on the second."
    """
    t = _norm(text)
    return "claimable" in t and (
        "queued > 0" in t or "queued>0" in t or "queued = 0" in t or "queued=0" in t
    )


def forbids_false_empty_exit(text):
    """True when the skill states that zero claimed rows is not by itself an exit.

    A skill can mention claimability and still tell the executor to stop on a
    zero-row claim; this checks for the explicit prohibition.
    """
    t = _norm(text)
    return "stall" in t and ("not an empty queue" in t or "never as an exit" in t
                             or "not a reason to stop" in t)


def forbids_fleet_config_credentials(text):
    """True when the skill still carries the post-2026-08-02 credential rule.

    Invariant 1 in cowork-skills/README.md. Regressing it reintroduces the
    empty-token push failure that broke every executor and the shared clone.
    """
    t = _norm(text)
    return "never read" in t and "fleet_config" in t


def forbids_remote_url_rewrite(text):
    """True when the skill still forbids rewriting origin.

    Invariant 2. Injecting a token into origin corrupts the clone the runner
    shares, so this outlives whatever credential scheme is current.

    Matches the prohibition however it is spelled. The live skills say "DO NOT
    rewrite origin" and never use the literal `set-url`, so an earlier version
    of this predicate that required `set-url` failed all sixteen compliant files
    — a checker that reports a false regression trains people to ignore it, so
    it accepts either spelling.
    """
    t = _norm(text)
    mentions = "set-url" in t or "rewrite origin" in t
    return mentions and ("do not" in t or "never" in t)


def forbids_stub_commits(text):
    """True when the skill still refuses fabricated commits.

    Invariant 5: DONE only after a verified push of a non-doc diff. Without this
    an executor facing an unimplementable prompt manufactures a filler commit
    and reports success, which is the same lie as the false-empty exit wearing
    different clothes.
    """
    t = _norm(text)
    return "stub commit" in t or "fabricate" in t


#: name -> (predicate, why it matters). Ordered most-recent-regression first.
CHECKS = (
    ("claimability_preflight", has_claimability_preflight,
     "must count QUEUED separately from claimable, so a deadlocked queue is not "
     "reported as an empty one"),
    ("no_false_empty_exit", forbids_false_empty_exit,
     "must state that queued>0 with 0 claimable is a STALL, never an exit"),
    ("no_fleet_config_credentials", forbids_fleet_config_credentials,
     "must not reintroduce reading credentials from fleet_config"),
    ("no_remote_url_rewrite", forbids_remote_url_rewrite,
     "must not rewrite origin with an injected token"),
    ("no_stub_commits", forbids_stub_commits,
     "must not allow fabricated commits to satisfy a task"),
)


def check_skill(text, name=None):
    """Run every invariant over one skill's text.

    Returns a dict — never raises, so a caller sweeping sixteen files does not
    lose the whole report to one unreadable one:

        {"name": str|None, "ok": bool, "failed": [str, ...],
         "findings": {check_name: bool, ...}}
    """
    findings = {}
    for check_name, predicate, _why in CHECKS:
        try:
            findings[check_name] = bool(predicate(text))
        except Exception:
            # A predicate that blows up is a failed check, not a crashed sweep.
            findings[check_name] = False
    failed = [k for k, v in findings.items() if not v]
    return {"name": name, "ok": not failed, "failed": failed, "findings": findings}


def why(check_name):
    """Human-readable reason a check exists. Empty string when unknown."""
    for name, _predicate, reason in CHECKS:
        if name == check_name:
            return reason
    return ""


def check_many(named_texts):
    """Check an iterable of (name, text) pairs. Returns a list of check_skill dicts."""
    return [check_skill(text, name=name) for name, text in named_texts]


def format_report(results):
    """Render check_many() output as lines a log can carry. Never raises."""
    lines = []
    for r in results:
        if r.get("ok"):
            lines.append("ok   %s" % (r.get("name") or "<unnamed>"))
            continue
        for f in r.get("failed") or []:
            lines.append("FAIL %s: %s — %s" % (r.get("name") or "<unnamed>", f, why(f)))
    return lines
