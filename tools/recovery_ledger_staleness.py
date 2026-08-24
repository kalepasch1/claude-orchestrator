#!/usr/bin/env python3
"""recovery_ledger_staleness.py — re-check that ledger evidence still exists, before a
recovery task is queued against it.

THE FAILURE THIS EXISTS FOR
---------------------------
`recover-never-again-lane-daemon-dirty-worktree` was queued from a ledger entry
classifying `claude-orchestrator-wt/never-again-lane-daemon` as RECOVERABLE_VALUE:
9 uncommitted paths whose tracked diff still applied cleanly to origin/master.

By the time the task ran, the worktree was GONE from disk and `.git/worktrees/` had no
admin dir for it, so its index and ORIG_HEAD went with it. Uncommitted content is not in
the object database, so there was nothing to `git diff HEAD` and nothing to apply. The
rescue ref that looks like a backup, `refs/orch-rescue/...-never-again-lane-daemon-9a14f094`,
points at the worktree's HEAD COMMIT — already an ancestor of origin/master. It captured
the base, not the dirty diff.

An executor then spent a full run re-deriving that. It will keep happening, because a
`dirty_worktree` verdict is a claim about a directory at one instant and the ledger
outlives the directory.

WHAT THIS DOES
--------------
Re-validates each `dirty_worktree` item in a ledger against the filesystem NOW and
reports which claims no longer hold, so a stale one can be closed instead of retried.

    python3 tools/recovery_ledger_staleness.py .orch/recovery-ledger-*.json
    python3 tools/recovery_ledger_staleness.py --json ledger.json
    python3 tools/recovery_ledger_staleness.py --strict ledger.json   # exit 1 if stale

Read-only and fail-soft, like every reconciler here: it never deletes, prunes, stashes or
resets anything, an unreadable ledger yields an empty report rather than a traceback, and
an item it cannot judge is reported as UNVERIFIABLE — never silently as fresh. "We could
not check" and "the evidence is gone" are different claims, and collapsing them is how a
real recoverable diff gets closed by mistake.
"""
import argparse
import json
import os
import subprocess
import sys

#: Item kinds whose evidence is uncommitted working-tree state, i.e. not in the object
#: database and therefore capable of evaporating between ledger and task.
PERISHABLE_KINDS = ("dirty_worktree",)

FRESH = "FRESH"
GONE = "EVIDENCE_GONE"
CLEAN = "EVIDENCE_CLEAN"
UNVERIFIABLE = "UNVERIFIABLE"


def _git(*args, cwd="."):
    """Read-only git call. Returns stdout, or "" on any failure."""
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True,
                           text=True, errors="replace", timeout=60)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def load_ledger(path):
    """Read a ledger. Fail-soft: {} on missing/unreadable/malformed input."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def is_perishable(item):
    """True when the item's evidence lives only in a working tree."""
    return isinstance(item, dict) and item.get("kind") in PERISHABLE_KINDS


def check_item(item):
    """Re-validate one ledger item NOW. Returns a verdict dict; never raises.

    FRESH         the directory exists and still carries uncommitted changes
    EVIDENCE_GONE the directory no longer exists — nothing to recover, close the task
    EVIDENCE_CLEAN the directory exists but is clean — the work was committed or lost
    UNVERIFIABLE  the item could not be judged; deliberately NOT treated as gone
    """
    if not isinstance(item, dict):
        return {"ref": "", "verdict": UNVERIFIABLE, "detail": "item is not an object"}

    ref = str(item.get("ref") or "")
    base = {"ref": ref, "kind": item.get("kind", ""),
            "classification": item.get("classification", "")}

    if not ref:
        return dict(base, verdict=UNVERIFIABLE, detail="item carries no ref")
    if not is_perishable(item):
        return dict(base, verdict=UNVERIFIABLE,
                    detail="kind %r is not working-tree evidence; nothing to re-check"
                           % item.get("kind"))

    if not os.path.isdir(ref):
        return dict(base, verdict=GONE, detail=(
            "worktree directory is gone. Uncommitted content is not in the object "
            "database, so there is nothing to `git diff HEAD` and nothing to apply. "
            "A rescue ref for this slug, if one exists, most likely captured the HEAD "
            "COMMIT rather than the dirty diff — check before assuming it is a backup."))

    status = _git("status", "--porcelain", cwd=ref)
    if status is None or status == "":
        # An empty status from a directory that IS a worktree means clean; from a
        # directory git refuses to read, _git also returns "". Distinguish them.
        if not _git("rev-parse", "--is-inside-work-tree", cwd=ref):
            return dict(base, verdict=UNVERIFIABLE,
                        detail="path exists but git cannot read it as a worktree")
        return dict(base, verdict=CLEAN, detail=(
            "worktree exists but `git status --porcelain` is empty; the uncommitted "
            "evidence this item recorded is no longer there"))

    return dict(base, verdict=FRESH,
                detail="worktree still carries %d uncommitted path(s)"
                       % len(status.splitlines()))


def check_ledger(ledger):
    """Re-validate every item. Returns a report dict. Never raises."""
    ledger = ledger if isinstance(ledger, dict) else {}
    items = ledger.get("items")
    items = items if isinstance(items, list) else []

    verdicts = [check_item(it) for it in items]
    perishable = [v for v in verdicts if v.get("kind") in PERISHABLE_KINDS]
    counts = {}
    for v in perishable:
        counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1

    stale = [v for v in perishable if v["verdict"] in (GONE, CLEAN)]
    return {
        "audit_fingerprint": ledger.get("audit_fingerprint", ""),
        "total_items": len(items),
        "perishable_items": len(perishable),
        "counts": counts,
        "stale": stale,
        "stale_refs": [v["ref"] for v in stale],
        "verdicts": perishable,
    }


def render(report):
    lines = [
        "%d item(s), %d carrying working-tree evidence"
        % (report["total_items"], report["perishable_items"]),
        "counts: %s" % (json.dumps(report["counts"], sort_keys=True) or "{}"),
    ]
    for v in report["verdicts"]:
        lines.append("  %-14s %s" % (v["verdict"], v["ref"]))
        lines.append("                 %s" % v["detail"])
    if report["stale"]:
        lines.append("")
        lines.append("%d stale claim(s): close these rather than retrying them — "
                     "retrying re-derives the same answer." % len(report["stale"]))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("ledger", nargs="+", help="recovery ledger JSON file(s)")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when any ledger claim is stale")
    args = ap.parse_args(argv)

    reports, stale_total = [], 0
    for path in args.ledger:
        report = check_ledger(load_ledger(path))
        report["ledger"] = path
        reports.append(report)
        stale_total += len(report["stale"])

    if args.json:
        print(json.dumps(reports if len(reports) > 1 else reports[0], indent=2))
    else:
        for report in reports:
            print("== %s" % report["ledger"])
            print(render(report))

    return 1 if (args.strict and stale_total) else 0


if __name__ == "__main__":
    sys.exit(main())
