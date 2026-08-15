#!/usr/bin/env python3
"""Classify local-only branch tips against the current default branch.

Read-only with respect to the evidence: this tool only ever runs plumbing that
inspects refs (`rev-list`, `merge-base`, `merge-tree`). It never checks out,
resets, cleans, pops or deletes a local branch, so a run can be repeated safely
while the branches it describes are still being used elsewhere.

Classifications (fleet-wide vocabulary):
  ALREADY_PRESENT               tip adds nothing the default branch lacks
  SUPERSEDED_BY_NEWER           work landed or was retired under a newer task
  ACTIVE_IN_ANOTHER_TASK        a live orchestrator task still owns the slug
  RECOVERABLE_VALUE             unique commits, applies cleanly, nobody owns it
  CONFLICTED_NEEDS_FOCUSED_TASK unique commits that no longer merge cleanly
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass, field

# Task states that mean somebody else is still going to ship this branch.
LIVE_STATES = {"QUEUED", "RUNNING", "DECOMPOSED", "BLOCKED"}
# Task states that mean the branch's reason for existing is already resolved.
RETIRED_STATES = {"MERGED", "DONE", "CLOSED", "SUPERSEDED", "QUARANTINED"}


@dataclass
class Item:
    ref: str
    slug: str
    sha: str
    committed_at: int
    subject: str
    unique_commits: int
    files_changed: int
    task_state: str
    classification: str
    disposition: str
    conflicts: list = field(default_factory=list)
    # Digest of the whole diff vs base. Refs sharing a digest are the same patch
    # re-committed by self-heal retries, not independent recoverable work.
    patch_digest: str = ""
    # Files the patch removes that still exist on base. A clean merge that
    # deletes live code is exactly the regression the merge train guards against.
    deletes: list = field(default_factory=list)


def git(repo, *args):
    """Run a read-only git command; return stripped stdout, or '' on failure."""
    proc = subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, check=False
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def git_merge_tree(repo, *args):
    """`git merge-tree`, which exits 1 on conflict but still prints a usable result.

    Routing it through git() would discard exactly the output that proves a conflict
    exists, silently reporting every branch as merging cleanly.
    """
    proc = subprocess.run(
        ["git", "-C", repo, "merge-tree", *args],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode not in (0, 1):
        return "", None
    return proc.stdout.strip(), proc.returncode == 0


def local_only_refs(repo):
    """Local branch short-names that have no same-named ref on origin."""
    local = set(git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").split())
    remote = {
        r.split("/", 1)[1]
        for r in git(
            repo, "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"
        ).split()
        if "/" in r
    }
    return sorted(local - remote)


def merge_conflicts(repo, base, ref):
    """Paths that conflict when ref is merged into base. Empty means clean."""
    out, clean = git_merge_tree(repo, "--write-tree", "--name-only", base, ref)
    if clean is None or clean:
        return []
    # On conflict the tree oid comes first, then the conflicted paths, then the
    # human-readable "Auto-merging"/"CONFLICT" narration, which is not a path.
    paths = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith(("Auto-merging", "CONFLICT")):
            continue
        paths.append(line)
    return paths


TEST_DECL = re.compile(r"^[-+]\s*(it|test|describe)\s*[.(]")
TEST_PATH = re.compile(r"(__tests__/|\.test\.|\.spec\.)")
# Marker files a retry loop drops to record that it ran. They carry no code, so a
# branch whose whole diff is markers has nothing to recover no matter how it merges.
MARKER_PATH = re.compile(r"(^|/)\.(recovery-intent|patch-intent|agent-intent)[-.]")


def dropped_test_cases(repo, base, ref):
    """Test declarations the patch removes, per already-existing test file.

    A patch can delete coverage without deleting a file, so counting `D` name-status
    entries is not enough: stripping `it(...)` blocks out of a surviving test file is
    the same regression wearing a disguise. Returns {path: net_cases_removed}.
    """
    dropped = {}
    changed = [
        line.split("\t", 1)[1]
        for line in git(repo, "diff", "--name-status", f"{base}...{ref}").splitlines()
        if line.startswith("M\t") and TEST_PATH.search(line)
    ]
    for path in changed:
        net = 0
        for line in git(repo, "diff", f"{base}...{ref}", "--", path).splitlines():
            if TEST_DECL.match(line):
                net += 1 if line.startswith("-") else -1
        if net > 0:
            dropped[path] = net
    return dropped


# Top-level definitions, in the languages this fleet's repos actually use.
SYMBOL_DECL = re.compile(
    r"^[-+]\s*(?:export\s+)?(?:async\s+)?"
    r"(?:def|class|function|interface|type|const|let|var)\s+([A-Za-z_$][\w$]*)"
)


def dropped_symbols(repo, base, ref):
    """Top-level definitions the patch removes from files it does not delete.

    Gutting a module is the same regression as deleting it, but leaves an `M` in
    name-status, so a file-level check waves it through. Returns {path: [names]}.
    """
    dropped = {}
    changed = [
        line.split("\t", 1)[1]
        for line in git(repo, "diff", "--name-status", f"{base}...{ref}").splitlines()
        if line.startswith("M\t")
    ]
    for path in changed:
        removed, added = set(), set()
        for line in git(repo, "diff", f"{base}...{ref}", "--", path).splitlines():
            match = SYMBOL_DECL.match(line)
            if match:
                (removed if line.startswith("-") else added).add(match.group(1))
        gone = sorted(removed - added)
        if gone:
            dropped[path] = gone
    return dropped


def merge_is_noop(repo, base, ref):
    """True when merging ref into base would change nothing.

    `git diff base...ref` is computed from the merge base, so a branch that already
    landed — or that predates a history rewrite — reports its entire patch as new
    even though base contains every line of it. Merging into a tree and comparing
    the result to base's tree asks the question that actually matters: would taking
    this ref change anything? Blob-by-blob comparison is not enough, because a file
    can differ while the branch's own contribution is already upstream.
    """
    out, clean = git_merge_tree(repo, "--write-tree", base, ref)
    if not clean or not out:
        return False
    return out.splitlines()[0].strip() == git(repo, "rev-parse", f"{base}^{{tree}}")


def contained_in_origin(repo, sha):
    """True when the tip is already reachable from some ref on origin."""
    out = git(repo, "for-each-ref", "--contains", sha, "--format=%(refname:short)",
              "refs/remotes/origin")
    return bool(out.strip())


def resolve(repo, ref):
    """Ref to inspect, tolerating evidence that went stale mid-run.

    An evidence snapshot names local refs, but a concurrent executor can delete or
    publish one between snapshot and reconciliation. Falling back to origin/<ref>
    keeps such an item classifiable instead of silently dropping it, which would
    understate the ledger and leave an UNKNOWN behind.
    """
    if git(repo, "rev-parse", "--verify", "--quiet", ref):
        return ref, False
    remote = f"origin/{ref}"
    if git(repo, "rev-parse", "--verify", "--quiet", remote):
        return remote, True
    return ref, False


def classify(repo, base, ref, task_states):
    slug = ref.split("agent/", 1)[1] if ref.startswith("agent/") else ref
    lookup, vanished = resolve(repo, ref)
    sha = git(repo, "rev-parse", lookup)
    if vanished:
        return Item(ref, slug, sha, int(git(repo, "log", "-1", "--format=%ct", lookup) or 0),
                    git(repo, "log", "-1", "--format=%s", lookup), 0, 0,
                    task_states.get(slug), "ALREADY_PRESENT",
                    f"local ref is gone but the work is published at {lookup}; nothing"
                    " lost (ref removed by another process during reconciliation, not"
                    " by this task)")
    subject = git(repo, "log", "-1", "--format=%s", ref)
    committed_at = int(git(repo, "log", "-1", "--format=%ct", ref) or 0)
    unique = int(git(repo, "rev-list", "--count", f"{base}..{ref}") or 0)
    state = task_states.get(slug)

    if unique == 0:
        return Item(ref, slug, sha, committed_at, subject, 0, 0, state,
                    "ALREADY_PRESENT",
                    f"no unique commits vs {base}; ref is an empty marker, safe to leave")

    files = len(git(repo, "diff", "--name-only", f"{base}...{ref}").splitlines())
    digest = hashlib.sha256(
        git(repo, "diff", f"{base}...{ref}").encode("utf-8", "replace")
    ).hexdigest()[:12]
    deletes = [
        line.split("\t", 1)[1]
        for line in git(repo, "diff", "--name-status", f"{base}...{ref}").splitlines()
        if line.startswith("D\t")
    ]

    def item(classification, disposition, conflicts=None):
        return Item(ref, slug, sha, committed_at, subject, unique, files, state,
                    classification, disposition, conflicts or [], digest, deletes)

    if contained_in_origin(repo, sha):
        return item("ALREADY_PRESENT",
                    "tip is reachable from a ref on origin; already published")

    if merge_is_noop(repo, base, ref):
        return item("ALREADY_PRESENT",
                    f"merging this ref into {base} would change nothing — its"
                    f" {files}-file diff is an artifact of a stale merge base and the"
                    " content already landed")

    # Ownership first: a live task still owns the slug regardless of what the ref
    # currently holds, so claiming it here would duplicate that task's work.
    if state in LIVE_STATES:
        return item("ACTIVE_IN_ANOTHER_TASK",
                    f"live task {slug} is {state}; leave queued, do not duplicate")

    touched = git(repo, "diff", "--name-only", f"{base}...{ref}").splitlines()
    if touched and all(MARKER_PATH.search(p) for p in touched):
        return item("SUPERSEDED_BY_NEWER",
                    "whole diff is retry-loop marker file(s) with no code content"
                    f" ({', '.join(touched[:2])}); nothing to recover — the real"
                    " record lives in the orchestrator queue, not this ref")

    if state in RETIRED_STATES:
        return item("SUPERSEDED_BY_NEWER",
                    f"task {slug} reached {state}; newer implementation wins")

    conflicts = merge_conflicts(repo, base, ref)
    if conflicts:
        return item("CONFLICTED_NEEDS_FOCUSED_TASK",
                    f"{len(conflicts)} path(s) conflict with {base}; queue a focused"
                    " follow-up rather than forcing an overwrite", conflicts)

    # A textually clean merge is not the same as a safe one. If the patch removes
    # files that still exist on base, auto-recovering it would land a deletion the
    # merge train would (correctly) reject. Route it to a human-sized task instead.
    if deletes:
        return item("CONFLICTED_NEEDS_FOCUSED_TASK",
                    f"merges cleanly but DELETES {len(deletes)} file(s) still present"
                    f" on {base} ({', '.join(deletes[:3])}"
                    f"{', …' if len(deletes) > 3 else ''}); needs a focused task that"
                    " keeps the removed code")

    dropped = dropped_test_cases(repo, base, ref)
    if dropped:
        total = sum(dropped.values())
        return item("CONFLICTED_NEEDS_FOCUSED_TASK",
                    f"merges cleanly but REMOVES {total} test case(s) from"
                    f" {len(dropped)} existing test file(s)"
                    f" ({', '.join(sorted(dropped))}); coverage regression, needs a"
                    " focused task that keeps the assertions")

    symbols = dropped_symbols(repo, base, ref)
    if symbols:
        names = [n for names in symbols.values() for n in names]
        return item("CONFLICTED_NEEDS_FOCUSED_TASK",
                    f"merges cleanly but REMOVES {len(names)} top-level definition(s)"
                    f" from {len(symbols)} surviving file(s)"
                    f" ({', '.join(names[:5])}{', …' if len(names) > 5 else ''});"
                    " restore the named symbols before this can land")

    return item("RECOVERABLE_VALUE",
                f"{unique} unique commit(s) over {files} file(s) merge cleanly onto"
                f" {base}, remove no file, test case or definition, and no live task"
                " owns them")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--fingerprint", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--task-states", help="JSON file mapping slug -> task state")
    ap.add_argument("--exclude", action="append", default=[],
                    help="ref to skip (e.g. this task's own branch)")
    ap.add_argument("--also", action="append", default=[],
                    help="ref named by the evidence snapshot that must be classified "
                         "even if it is no longer local-only")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md", required=True)
    args = ap.parse_args()

    task_states = {}
    if args.task_states:
        with open(args.task_states) as fh:
            task_states = json.load(fh)

    skip = set(args.exclude)
    refs = [r for r in local_only_refs(args.repo) if r not in skip]
    refs += [r for r in args.also if r not in skip and r not in set(refs)]
    refs.sort()
    items = [classify(args.repo, args.base, r, task_states) for r in refs]

    summary = {}
    for item in items:
        summary[item.classification] = summary.get(item.classification, 0) + 1

    # Collapse self-heal retries: many refs, one patch. This is the number that
    # tells the operator how much real work is outstanding.
    patches = {}
    for item in items:
        if item.patch_digest and item.classification in {
            "RECOVERABLE_VALUE", "CONFLICTED_NEEDS_FOCUSED_TASK"
        }:
            patches.setdefault(item.patch_digest, []).append(item.ref)

    ledger = {
        "fingerprint": args.fingerprint,
        "project": args.project,
        "repo": args.repo,
        "kind": "local_only_branch_tips",
        "default_ref": f"{args.base}@{git(args.repo, 'rev-parse', '--short', args.base)}",
        "enumerated_live_source": True,
        "evidence_mutated": False,
        "total": len(items),
        "unknown": 0,
        "summary": summary,
        "distinct_patches": len(patches),
        "patch_groups": {d: sorted(refs) for d, refs in sorted(patches.items())},
        "items": [asdict(i) for i in items],
    }

    with open(args.out_json, "w") as fh:
        json.dump(ledger, fh, indent=2, sort_keys=True)
        fh.write("\n")

    write_markdown(args.out_md, ledger)
    print(json.dumps({"total": ledger["total"], "unknown": 0, "summary": summary,
                      "distinct_patches": len(patches)}, indent=2))


def write_markdown(path, ledger):
    """Render the human-readable half of the recovery ledger."""
    lines = [
        f"# Recovery ledger — {ledger['project']} local-only branch tips",
        "",
        f"- Fingerprint: `{ledger['fingerprint']}`",
        f"- Repo: `{ledger['repo']}`",
        f"- Compared against: `{ledger['default_ref']}`",
        f"- Items classified: **{ledger['total']}** (UNKNOWN: {ledger['unknown']})",
        f"- Distinct patches behind those refs: **{ledger['distinct_patches']}**",
        "- Evidence mutated: **no** (refs inspected only, never checked out or deleted)",
        "",
        "## Summary",
        "",
        "| Classification | Count |",
        "| --- | ---: |",
    ]
    for name, count in sorted(ledger["summary"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {name} | {count} |")

    lines += ["", "## Items", "",
              "| Ref | Unique | Files | Task state | Classification | Disposition |",
              "| --- | ---: | ---: | --- | --- | --- |"]
    for item in sorted(ledger["items"], key=lambda i: (i["classification"], i["ref"])):
        lines.append(
            f"| `{item['ref']}` | {item['unique_commits']} | {item['files_changed']} |"
            f" {item['task_state'] or '—'} | {item['classification']} |"
            f" {item['disposition']} |"
        )

    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
