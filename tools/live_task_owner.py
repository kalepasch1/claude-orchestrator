#!/usr/bin/env python3
"""Does a live orchestrator task already own this worktree?

`tools/reconcile_worktree_evidence.py` classifies a dirty worktree by asking git:
does the diff apply, is the branch published, is the base newer. Git cannot answer
the question that actually matters for a worktree that is dirty *right now* —
whether an agent is editing it this second.

On 2026-08-23 a reconciliation pass found three dirty worktrees
(`canary-deepseek-1`, `madeus-group-3`, `orch-cross-project-depends`) and called
all three RECOVERABLE_VALUE. All three were owned by tasks in state RUNNING under
another executor account. "Recovering" them would have raced a live agent for the
same files and re-delivered work already in flight — the one thing the recovery
contract explicitly forbids.

This module answers that question from task state. It is deliberately standalone:
it takes a slug and returns an owner, so a caller decides what to do with the
answer, and it can be wired into any reconciler without either of them importing
the other.

Fail-soft throughout: if task state cannot be read, every lookup reports "no known
owner" rather than raising. A reconciler that cannot reach the database must still
produce a ledger — it will simply be more conservative about what it calls active,
and `owner_lookup(..., strict=True)` inverts that for callers who would rather
defer than risk a collision.
"""

from __future__ import annotations

import os
import re

# States meaning somebody else is still going to ship this work. Kept in sync with
# tools/reconcile_local_branch_tips.py, which uses the same vocabulary.
LIVE_STATES = frozenset({"QUEUED", "RUNNING", "DECOMPOSED", "BLOCKED"})
RETIRED_STATES = frozenset({"MERGED", "DONE", "CLOSED", "SUPERSEDED",
                            "QUARANTINED", "DEPLOYED_AND_VERIFIED"})

# A worktree directory is named for its slug, but the runner truncates long slugs
# and sometimes appends a short sha, so an exact match is not enough.
_TRAILING_SHA = re.compile(r"[ _-][0-9a-f]{7,40}$")


def slug_from_path(path: str) -> str:
    """Best-effort slug for a worktree directory.

    Worktree names carry noise the task table does not: a trailing short sha, and
    occasionally a space-separated suffix from a malformed registration. Strip it
    so `canary-deepseek-1 15227eb7` still resolves to `canary-deepseek-1`.
    """
    if not path:
        return ""
    # normpath("") is ".", which would become a slug named "." — a lookup that
    # can never match but also never looks wrong. Return empty instead.
    name = os.path.basename(os.path.normpath(path))
    name = name.split(" ")[0]
    if name in (".", ".."):
        return ""
    return _TRAILING_SHA.sub("", name)


def _load_task_states() -> "dict[str, str]":
    """slug -> state for every task, or {} when task state is unreachable."""
    try:
        import sys
        for cand in (os.environ.get("ORCH_RUNNER_DIR", ""),
                     os.path.expanduser(
                         "~/Documents/beethoven/claude-orchestrator/runner")):
            if cand and os.path.isfile(os.path.join(cand, ".env")):
                sys.path.insert(0, cand)
                break
        import db  # noqa: PLC0415 - deferred; import cost only when actually used
        # Filter server-side. An unfiltered scan of `tasks` returns exactly the
        # 1000-row page cap and the runner's own truncated-scan guard flags it:
        # the far end of the queue would be invisible, so a live owner past the
        # cap would read as "nobody owns this" — the precise wrong answer.
        # Only live states can own anything, and they are the small minority.
        rows = db.select_all("tasks", params={
            "select": "slug,state",
            "state": "in.(%s)" % ",".join(sorted(LIVE_STATES)),
        })
    except Exception:  # noqa: BLE001 - fail-soft, see module docstring
        return {}
    states: dict[str, str] = {}
    for row in rows or []:
        slug, state = row.get("slug"), row.get("state")
        if not slug:
            continue
        # A slug can appear more than once across attempts; a live state wins,
        # because one live owner is enough to make the work somebody else's.
        if states.get(slug) in LIVE_STATES:
            continue
        states[slug] = state or ""
    return states


def owner_lookup(states: "dict[str, str] | None" = None, strict: bool = False):
    """Return `is_owned(path) -> (slug, state) | None`.

    `states` is injectable so callers (and tests) can supply task state instead of
    reading the database. `strict=True` treats an unreadable task table as "assume
    owned", for callers that would rather defer than race a live agent.
    """
    if states is None:
        states = _load_task_states()
    unreachable = not states

    def is_owned(path: str):
        slug = slug_from_path(path)
        if not slug:
            return None
        state = states.get(slug)
        if state is None:
            # Longest matching prefix: the runner truncates long slugs when it
            # names a worktree, so the directory is a prefix of the real slug.
            candidates = [s for s in states if s.startswith(slug)]
            if candidates:
                best = max(candidates, key=len)
                slug, state = best, states[best]
        if state is None:
            if unreachable and strict:
                return (slug, "UNKNOWN")
            return None
        return (slug, state) if state in LIVE_STATES else None

    return is_owned
