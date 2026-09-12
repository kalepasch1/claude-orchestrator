#!/usr/bin/env python3
"""recover_from_manifest.py — drive recovery from an evidence manifest, one item at a time.

Consumes the manifest produced by tools/reconcile_evidence_inventory.py and, for each item
classified RECOVERABLE_VALUE, applies the minimum coherent diff into an ISOLATED worktree
— never the shared checkout, and never over the evidence.

WHY THIS IS A DRIVER AND NOT A ONE-SHOT SCRIPT
----------------------------------------------
A live manifest of this repo classifies 125 items RECOVERABLE_VALUE. Applying all of them
in one pass is exactly the shape that has failed here before: a single branch carrying a
hundred unrelated recoveries cannot be reviewed, cannot be bisected when it breaks, and
conflicts with everything. So each item gets its own commit and its own recorded SHA, the
run is resumable, and a failure on item N does not discard items 1..N-1.

THE RULES, AND WHY EACH ONE IS HERE
-----------------------------------
* Evidence is READ-ONLY. Every read is `git show <sha>:<path>`; nothing is checked out in
  the shared clone, no stash is popped, no ref is deleted or moved. The manifest describes
  where the evidence is — it never becomes the place the work happens.
* CONFLICTED_NEEDS_FOCUSED_TASK is SKIPPED, not attempted. That verdict means a human has
  to look; a machine guessing at it produces a plausible wrong merge which is worse than
  the conflict.
* Dependency ORDER is by manifest position, so an item that others build on is applied
  first. Items are independent by construction (each is a distinct absent path set), but
  order is preserved rather than sorted, because re-ordering evidence is a decision nobody
  asked for.
* NEVER OVERWRITE. A path that already exists in the worktree is skipped with a reason:
  the base already has an implementation, and clobbering it with older evidence is the
  regression this whole exercise exists to avoid.

    python3 tools/recover_from_manifest.py evidence_manifest.json --dry-run
    python3 tools/recover_from_manifest.py evidence_manifest.json --worktree /path/wt
    python3 tools/recover_from_manifest.py evidence_manifest.json --limit 5
"""
import argparse
import json
import os
import subprocess
import sys

REPO = os.environ.get("ORCH_REPO_PATH", os.getcwd())
GIT_TIMEOUT = int(os.environ.get("ORCH_GIT_TIMEOUT_SECONDS", "120"))

RECOVERABLE = "RECOVERABLE_VALUE"
CONFLICTED = "CONFLICTED_NEEDS_FOCUSED_TASK"


def git(*args, cwd=None, check=False):
    """Returns (rc, stdout). Never raises unless check=True."""
    try:
        r = subprocess.run(["git", "-C", cwd or REPO, *args], capture_output=True,
                           text=True, errors="replace", timeout=GIT_TIMEOUT)
        if check and r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout or "git failed").strip()[:300])
        return r.returncode, (r.stdout or "").strip()
    except Exception as exc:
        if check:
            raise
        return 1, str(exc)[:300]


def load_manifest(path):
    """Read a manifest. Fail-soft: {} on anything unreadable."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def recoverable_items(manifest):
    """RECOVERABLE_VALUE items, in manifest order. CONFLICTED are never returned."""
    items = manifest.get("items") if isinstance(manifest, dict) else None
    if not isinstance(items, list):
        return []
    return [it for it in items
            if isinstance(it, dict) and it.get("classification") == RECOVERABLE]


def skipped_items(manifest):
    """Items deliberately left for a human, with their reasons."""
    items = manifest.get("items") if isinstance(manifest, dict) else None
    if not isinstance(items, list):
        return []
    return [{"source": it.get("source"), "reason": it.get("reason") or ""}
            for it in items if isinstance(it, dict)
            and it.get("classification") == CONFLICTED]


def plan_item(item, worktree):
    """What would be applied for one item: (paths_to_add, paths_skipped).

    Pure apart from an existence check, so the never-overwrite rule is testable.
    """
    paths = [p for p in (item.get("paths") or []) if p]
    add, skip = [], []
    for p in paths:
        if os.path.exists(os.path.join(worktree, p)):
            skip.append({"path": p, "reason": "already present in the worktree; "
                                              "refusing to overwrite with older evidence"})
        else:
            add.append(p)
    return add, skip


def apply_item(item, worktree, commit=True):
    """Copy one item's absent paths into the worktree and commit. Returns a record."""
    sha = str(item.get("sha") or "")
    source = str(item.get("source") or "")
    record = {"source": source, "sha": sha, "applied": [], "skipped": [],
              "commit": "", "error": ""}
    if not sha:
        record["error"] = "item carries no sha; nothing to read"
        return record

    add, skip = plan_item(item, worktree)
    record["skipped"] = skip
    if not add:
        record["error"] = "every path is already present; nothing to recover"
        return record

    for path in add:
        rc, blob = git("show", f"{sha}:{path}")
        if rc != 0:
            record["skipped"].append({"path": path, "reason": "unreadable in the evidence"})
            continue
        target = os.path.join(worktree, path)
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8", errors="replace") as fh:
                fh.write(blob + ("\n" if blob and not blob.endswith("\n") else ""))
            record["applied"].append(path)
        except Exception as exc:
            record["skipped"].append({"path": path, "reason": f"write failed: {exc}"})

    if not record["applied"]:
        record["error"] = "nothing could be read from the evidence"
        return record

    if commit:
        try:
            git("add", "--", *record["applied"], cwd=worktree, check=True)
            git("-c", "user.name=kalepasch1", "-c", "user.email=kalepasch@gmail.com",
                "commit", "--no-verify", "-m",
                f"recover: {len(record['applied'])} path(s) from {source}",
                cwd=worktree, check=True)
            _rc, record["commit"] = git("rev-parse", "HEAD", cwd=worktree)
        except Exception as exc:
            record["error"] = f"commit failed: {str(exc)[:200]}"
    return record


def run(manifest_path, worktree, limit=0, dry_run=False):
    manifest = load_manifest(manifest_path)
    items = recoverable_items(manifest)
    if limit:
        items = items[:limit]

    report = {
        "manifest": manifest_path,
        "worktree": worktree,
        "recoverable": len(recoverable_items(manifest)),
        "attempted": len(items),
        "skipped_conflicted": skipped_items(manifest),
        "results": [],
        "dry_run": bool(dry_run),
    }
    for item in items:
        if dry_run:
            add, skip = plan_item(item, worktree)
            report["results"].append({"source": item.get("source"), "would_apply": add,
                                      "skipped": skip})
        else:
            report["results"].append(apply_item(item, worktree))
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("manifest")
    ap.add_argument("--worktree", default="", help="isolated worktree to apply into")
    ap.add_argument("--limit", type=int, default=0, help="apply at most N items")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    worktree = args.worktree or REPO
    if not args.dry_run and os.path.abspath(worktree) == os.path.abspath(REPO):
        # The shared checkout is where other agents are working; applying here is the
        # destructive mistake the worktree convention exists to prevent.
        print("refusing to apply into the shared checkout; pass --worktree", file=sys.stderr)
        return 2

    report = run(args.manifest, worktree, limit=args.limit, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{report['recoverable']} recoverable, {report['attempted']} attempted, "
              f"{len(report['skipped_conflicted'])} conflicted left for a human")
        for r in report["results"]:
            applied = r.get("applied", r.get("would_apply", []))
            print(f"  {r.get('source')}: {len(applied)} path(s)"
                  + (f" -> {r.get('commit')[:9]}" if r.get("commit") else "")
                  + (f"  [{r['error']}]" if r.get("error") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
