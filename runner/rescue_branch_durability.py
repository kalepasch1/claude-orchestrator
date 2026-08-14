#!/usr/bin/env python3
"""rescue_branch_durability.py — the provenance record must survive this disk.

The lease-night recovery directive ends with: *"Do NOT delete the rescue branches; they are the
provenance record."* Correct, and not sufficient. Verified on Mac 1, 2026-08-05:

    34 `hotfix/stash-rescue-*` branches exist locally.  ZERO are on origin.

So the record that proves what was rescued — the only remaining copy of work the fleet already
lost once — lives on exactly one machine's local disk. Nobody has to delete it for it to be
gone. That is the same shape as the loss it documents, one level up.

`branch_durability.py` already solves this problem for `agent/*`: archive the tip under
`refs/archive/`, push to origin, and never delete what is not proven to survive. This module
simply points those primitives at the rescue namespaces, because the branches that hold
irreplaceable work are the ones least covered by any sweep.

DEFAULTS ARE READ-ONLY. `sweep()` reports; `sweep(share=True)` pushes. Nothing here ever
deletes a branch — for these branches deletion is never the right answer, so the capability
is simply absent rather than guarded. Fail-soft per CLAUDE.md.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO_DEFAULT = os.path.dirname(HERE)

#: Branch namespaces that hold recovered work. Local-only is a defect for all of them.
RESCUE_PREFIXES = tuple(
    p.strip() for p in os.environ.get(
        "ORCH_RESCUE_BRANCH_PREFIXES",
        "hotfix/stash-rescue-,hotfix/sentinel-rescue-,recovery/",
    ).split(",") if p.strip()
)


def _durability():
    """The shared primitives. Returns None when unavailable — callers degrade, never crash."""
    try:
        import branch_durability
        return branch_durability
    except Exception:
        return None


def is_rescue_branch(name):
    """True when `name` is in a rescue namespace. Never raises."""
    try:
        branch = str(name or "").strip().lstrip("* ").strip()
        return any(branch.startswith(prefix) for prefix in RESCUE_PREFIXES)
    except Exception:
        return False


def list_rescue_branches(repo=None, lister=None):
    """Local rescue branches, sorted. Fail-soft -> []."""
    try:
        repo = repo or REPO_DEFAULT
        if lister is not None:
            raw = lister(repo)
        else:
            durability = _durability()
            if durability is None:
                return []
            _, raw, _ = durability._git(repo, "branch", "--list", "--format=%(refname:short)")
        return sorted(b.strip() for b in (raw or "").splitlines()
                      if b.strip() and is_rescue_branch(b))
    except Exception:
        return []


def audit(repo=None, branches=None, on_origin=None):
    """Which rescue branches exist only on this disk.

    Returns {"total", "local_only", "durable", "at_risk": [...], "reason"}. `at_risk` is the
    list that matters: those branches are one disk away from being the third loss in this saga.

    `on_origin` is injectable for tests; it defaults to branch_durability.is_on_origin, which
    fails CLOSED (unproven means at risk). Never raises.
    """
    report = {"total": 0, "local_only": 0, "durable": 0, "at_risk": [], "reason": ""}
    try:
        repo = repo or REPO_DEFAULT
        branches = list_rescue_branches(repo) if branches is None else list(branches)
        report["total"] = len(branches)

        if on_origin is None:
            durability = _durability()
            if durability is None:
                report["at_risk"] = list(branches)
                report["local_only"] = len(branches)
                report["reason"] = ("branch_durability unavailable — cannot prove any rescue "
                                    "branch is on origin, so all are treated as at risk")
                return report
            on_origin = lambda branch: durability.is_on_origin(repo, branch)  # noqa: E731

        for branch in branches:
            try:
                safe = bool(on_origin(branch))
            except Exception:
                safe = False   # fail closed: unproven is at risk
            if safe:
                report["durable"] += 1
            else:
                report["local_only"] += 1
                report["at_risk"].append(branch)

        if report["at_risk"]:
            report["reason"] = (
                f"{len(report['at_risk'])} of {report['total']} rescue branches exist only on "
                f"this disk — the provenance record for work the fleet already lost once is "
                f"itself unbacked")
    except Exception:
        report["reason"] = "rescue branch audit failed"
    return report


def sweep(repo=None, share=False, branches=None, on_origin=None, sharer=None, archiver=None):
    """Make the rescue record durable. READ-ONLY unless `share=True`.

    For each at-risk branch: archive the tip under `refs/archive/` (cheap, one ref write, and
    it survives `git gc` regardless of what happens next), then — only when asked — push it to
    origin. Never deletes anything.

    Returns {"audit", "archived": [...], "shared": [...], "failed": [...]}. Never raises.
    """
    result = {"audit": {}, "archived": [], "shared": [], "failed": []}
    try:
        repo = repo or REPO_DEFAULT
        report = audit(repo=repo, branches=branches, on_origin=on_origin)
        result["audit"] = report

        durability = _durability()
        if archiver is None and durability is not None:
            archiver = lambda branch: durability.archive_branch(  # noqa: E731
                repo, branch, reason="rescue-provenance")
        if sharer is None and durability is not None:
            sharer = lambda branch: durability.try_share(repo, branch)  # noqa: E731

        for branch in report.get("at_risk", []):
            if archiver is not None:
                try:
                    if archiver(branch):
                        result["archived"].append(branch)
                except Exception:
                    result["failed"].append(branch)
            if share and sharer is not None:
                try:
                    if sharer(branch):
                        result["shared"].append(branch)
                    else:
                        result["failed"].append(branch)
                except Exception:
                    result["failed"].append(branch)
    except Exception:
        pass
    return result


def render(result):
    """Operator summary. Never raises."""
    try:
        report = (result or {}).get("audit", result) or {}
        lines = ["RESCUE BRANCH DURABILITY", "=" * 24,
                 f"  {report.get('total', 0)} rescue branches"
                 f"  ·  {report.get('durable', 0)} on origin"
                 f"  ·  {report.get('local_only', 0)} LOCAL ONLY"]
        if report.get("reason"):
            lines.append(f"  {report['reason']}")
        at_risk = report.get("at_risk") or []
        for branch in at_risk[:10]:
            lines.append(f"    at risk: {branch}")
        if len(at_risk) > 10:
            lines.append(f"    ... and {len(at_risk) - 10} more")
        if isinstance(result, dict):
            if result.get("archived"):
                lines.append(f"  archived {len(result['archived'])} tip(s) under refs/archive/")
            if result.get("shared"):
                lines.append(f"  pushed {len(result['shared'])} branch(es) to origin")
            if result.get("failed"):
                lines.append(f"  FAILED on {len(result['failed'])} — still local-only")
        if at_risk and not (isinstance(result, dict) and result.get("shared")):
            lines.append("  run with --share to push them to origin")
        return "\n".join(lines)
    except Exception:
        return "rescue branch durability report unavailable"


def run(repo=None, share=None):
    """Entry point for the periodic scheduler. Never raises."""
    try:
        if share is None:
            share = os.environ.get("ORCH_SHARE_RESCUE_BRANCHES", "true").lower() in (
                "1", "true", "yes", "on")
        result = sweep(repo=repo, share=share)
        print(render(result), flush=True)
        return result
    except Exception:
        return {"audit": {}, "archived": [], "shared": [], "failed": []}


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    repo = next((a for a in argv if not a.startswith("-")), REPO_DEFAULT)
    result = sweep(repo=repo, share="--share" in argv)
    print(render(result))
    return 1 if result.get("audit", {}).get("at_risk") else 0


if __name__ == "__main__":
    sys.exit(main())
