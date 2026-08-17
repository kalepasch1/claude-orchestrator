#!/usr/bin/env python3
"""
reconcile_agent_branches.py — classify agent/* branches against the default branch.

WHY A MODULE INSTEAD OF ANOTHER docs/recovery/*.md
---------------------------------------------------
This repo has accumulated a docs/recovery/chatgpt-local-reconcile-beethoven-<fp>-*.md
for every reconcile task that has run. Each one re-derived the same classification by
hand with ad-hoc shell, and each one is a snapshot that is stale the moment it lands.
That is why the same reconcile keeps coming back: nothing carried the RULE forward, only
the answer. This module carries the rule.

The classification is pure — it takes an already-collected view of the repository and
returns verdicts — so it is unit-testable without a repo, without network, and without
the multi-minute git walk that collecting the view requires.

THE RULE THAT KEEPS BEING GOT WRONG
-----------------------------------
A branch that exists on the remote ALREADY HAS durable provenance. The reconciliation
contract says do not duplicate work already represented by a live task or remote branch,
so an unmerged branch is never "recoverable value to import" — it is work waiting on the
merge train. Re-importing its files onto a second branch forks one change into two and
hands the train a conflict, which is exactly the "still conflicts after N redos" failure
that several of these tasks have been stuck on.

FAIL-SOFT
---------
Every function is total: a malformed observation is ESCALATED, never dropped. A dropped
item is precisely the UNKNOWN the completion criterion forbids.
"""
import re

ALREADY_PRESENT = "ALREADY_PRESENT"
SUPERSEDED_BY_NEWER = "SUPERSEDED_BY_NEWER"
ACTIVE_IN_ANOTHER_TASK = "ACTIVE_IN_ANOTHER_TASK"
RECOVERABLE_VALUE = "RECOVERABLE_VALUE"
CONFLICTED_NEEDS_FOCUSED_TASK = "CONFLICTED_NEEDS_FOCUSED_TASK"

VERDICTS = (ALREADY_PRESENT, SUPERSEDED_BY_NEWER, ACTIVE_IN_ANOTHER_TASK,
            RECOVERABLE_VALUE, CONFLICTED_NEEDS_FOCUSED_TASK)

# Build/scratch output a sweep captured. Never source value.
_NOISE = [
    re.compile(p) for p in (
        r"^node_modules/", r"^\.venv/", r"^dist/", r"^\.output/", r"^coverage/",
        r"^\.runtime/", r"^batch_chunks/", r"^__pycache__/",
        r"^\.commit(-message)?\.(txt|sh)$", r"^\.recovery-intent-",
        r"^\.markdownlint\.json$", r"^docs/.*-stub\.md$",
        r"\.(log|map|lock|pyc)$",
    )
]


def is_noise_path(path):
    """True when the path is build/scratch output rather than source. Never raises."""
    try:
        return any(rx.search(path) for rx in _NOISE)
    except Exception:
        return False


def signal_paths(paths):
    """Source paths only, with build/scratch noise removed. Never raises."""
    try:
        return [p for p in (paths or []) if isinstance(p, str) and p and not is_noise_path(p)]
    except Exception:
        return []


def classify_branch(ref, merged=False, adds_paths_absent_from_base=(),
                    has_live_task=False, conflicted=False):
    """Classify one branch -> (verdict, reason, retains_value). Total; never raises."""
    try:
        name = str(ref or "").strip()
        if not name:
            return (CONFLICTED_NEEDS_FOCUSED_TASK,
                    "observation carried no ref; escalated rather than dropped", True)

        if merged:
            return (ALREADY_PRESENT,
                    "branch is an ancestor of the base; its work is in merged history", False)

        if conflicted:
            return (CONFLICTED_NEEDS_FOCUSED_TASK,
                    "cannot merge cleanly; queue a focused rebase rather than forcing it", True)

        if has_live_task:
            return (ACTIVE_IN_ANOTHER_TASK,
                    "a live orchestrator task already owns this branch; do not duplicate", True)

        signal = signal_paths(adds_paths_absent_from_base)
        if not signal:
            return (SUPERSEDED_BY_NEWER,
                    "unmerged, but adds no source path the base lacks — the base already "
                    "carries an equal or newer implementation", False)

        return (ACTIVE_IN_ANOTHER_TASK,
                "unmerged and adds %d source path(s) absent from base (e.g. %s); the remote "
                "branch IS the durable provenance — leave it for the merge train, do not "
                "re-import" % (len(signal), ", ".join(signal[:3])), True)
    except Exception as exc:
        return (CONFLICTED_NEEDS_FOCUSED_TASK,
                "classification failed (%s); escalated rather than dropped" % exc, True)


def reconcile(observations):
    """Classify every observation. Returns a summary whose `unknown` is 0 by construction."""
    by_verdict = {v: 0 for v in VERDICTS}
    retained = []
    total = 0
    for obs in observations or ():
        total += 1
        try:
            verdict, _reason, keeps = classify_branch(
                obs.get("ref"),
                merged=obs.get("merged", False),
                adds_paths_absent_from_base=obs.get("adds_paths_absent_from_base", ()),
                has_live_task=obs.get("has_live_task", False),
                conflicted=obs.get("conflicted", False))
        except Exception:
            verdict, keeps = CONFLICTED_NEEDS_FOCUSED_TASK, True
        by_verdict[verdict] += 1
        if keeps:
            retained.append(str((obs or {}).get("ref", "(unnamed)")))
    return {"total": total, "by_verdict": by_verdict, "retained": retained, "unknown": 0}
