#!/usr/bin/env python3
"""Collapse a stranded-branch inventory into FAMILIES, and separate unique work from recounting.

Read-only. Mutates nothing, requeues nothing, merges nothing.

Why this exists. Batch 2 ended on an open question it could not answer from line counts alone:
the `chatgpt-local-reconcile-*` family showed 8 branches and ~45% of all stranded lines, and
"either it is real work that needs a lane, or it is a loop generating branches faster than the
train can drain them — and those two call for opposite responses."

Per-branch line counts cannot tell those apart, because a cumulative family re-commits its
predecessors' output. Each successive branch legitimately shows the earlier branches' files in
its diff against master, so the SAME blob is counted once per branch that carries it. The naive
total is then an artifact of how many times the loop ran, not a measure of recoverable work.

This module counts each unique (path, blob-sha) exactly once, and classifies each branch:

  duplicate  - its tip commit is identical to another branch's tip
  subsumed   - every file it changes is present, byte-identical, in a larger sibling
  distinct   - it carries at least one blob no sibling has

`subsumed` and `duplicate` are the only classifications this module will assert, and both rest
on blob-sha equality — the evidence bar the earlier batches set. Anything else is `distinct`,
never "probably superseded". A branch is only ever safe to close when a named sibling provably
contains all of its bytes.
"""
import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict

# Machine-generated evidence ledgers. Real artifacts, but their line count is output volume,
# not authored work, and including them overstates a family by an order of magnitude.
GENERATED_PATTERNS = [
    r"^docs/recovery-ledger/.*\.json$",
    r"^\.recovery-intent-.*\.txt$",
    r"^docs/recovery/.*\.json$",
]
_GENERATED = re.compile("|".join(GENERATED_PATTERNS))

# Strip the trailing content hash / slice suffix so sibling branches group together.
_HASH_SUFFIX = re.compile(r"[-_][0-9a-f]{8,}$")
_SLICE_SUFFIX = re.compile(r"-slice-\d+.*$")


def git(*args, cwd=None):
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return out.stdout.strip()


def is_generated(path):
    return bool(_GENERATED.search(path or ""))


def family_key(slug, depth=3):
    """The stable prefix shared by sibling branches from one generator."""
    s = _SLICE_SUFFIX.sub("", slug or "")
    s = _HASH_SUFFIX.sub("", s)
    return "-".join(s.split("-")[:depth]) or (slug or "")


def branch_blobs(branch, base="origin/master", cwd=None):
    """{(path, blob_sha): added_lines} for one branch's diff against base."""
    out = {}
    for line in git("diff", "--numstat", f"{base}...{branch}", cwd=cwd).splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, _removed, path = parts
        ls = git("ls-tree", branch, "--", path, cwd=cwd).split()
        sha = ls[2] if len(ls) >= 3 else f"missing:{path}"
        out[(path, sha)] = int(added) if added.isdigit() else 0
    return out


def tip(branch, cwd=None):
    return git("rev-parse", branch, cwd=cwd)


def classify(branch_map, tips):
    """Label every branch duplicate / subsumed / distinct on blob-sha evidence only.

    branch_map: {branch: {(path, sha): added}}
    tips:       {branch: commit sha}
    """
    branches = sorted(branch_map, key=lambda b: (-len(branch_map[b]), b))
    result, seen_tips = {}, {}
    for b in branches:
        t = tips.get(b)
        if t and t in seen_tips:
            result[b] = {"class": "duplicate", "same_as": seen_tips[t],
                         "why": f"tip commit {t[:8]} is identical to {seen_tips[t]}"}
            continue
        if t:
            seen_tips[t] = b
        mine = set(branch_map[b])
        container = None
        for other in branches:
            if other == b or result.get(other, {}).get("class") == "duplicate":
                continue
            if len(branch_map[other]) <= len(mine):
                continue
            if mine and mine <= set(branch_map[other]):
                container = other
                break
        if container:
            result[b] = {"class": "subsumed", "same_as": container,
                         "why": f"every changed file is byte-identical inside {container}"}
        else:
            result[b] = {"class": "distinct", "same_as": None,
                         "why": "carries at least one blob no sibling has"}
    return result


def analyze_family(branches, base="origin/master", cwd=None):
    """Unique-vs-recounted totals plus a per-branch classification for one family."""
    branch_map = {b: branch_blobs(b, base=base, cwd=cwd) for b in branches}
    tips = {b: tip(b, cwd=cwd) for b in branches}
    classes = classify(branch_map, tips)

    naive = sum(sum(m.values()) for m in branch_map.values())
    unique = {}
    for m in branch_map.values():
        unique.update(m)
    unique_total = sum(unique.values())
    generated = sum(v for (p, _s), v in unique.items() if is_generated(p))
    return {
        "branches": len(branches),
        "naive_added": naive,
        "unique_added": unique_total,
        "recounted_added": naive - unique_total,
        "generated_added": generated,
        "authored_added": unique_total - generated,
        "classes": classes,
        "distinct": sorted(b for b, c in classes.items() if c["class"] == "distinct"),
        "closable": sorted(b for b, c in classes.items() if c["class"] in ("duplicate", "subsumed")),
    }


def analyze(slugs, base="origin/master", cwd=None, prefix="origin/agent/", min_size=2):
    """Group slugs into families and analyze every family with more than one branch."""
    fams = defaultdict(list)
    for slug in slugs:
        fams[family_key(slug)].append(prefix + slug if not slug.startswith(prefix) else slug)
    out = {}
    for key, branches in fams.items():
        if len(branches) < min_size:
            continue
        out[key] = analyze_family(sorted(branches), base=base, cwd=cwd)
    return out


def render(report):
    lines = ["| family | branches | naive + | unique + | recounted | generated | authored | closable |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for key, f in sorted(report.items(), key=lambda kv: -kv[1]["naive_added"]):
        lines.append(f"| `{key}` | {f['branches']} | {f['naive_added']} | {f['unique_added']} | "
                     f"{f['recounted_added']} | {f['generated_added']} | {f['authored_added']} | "
                     f"{len(f['closable'])} |")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inventory", required=True, help="JSON from stranded_branch_inventory.py")
    ap.add_argument("--base", default="origin/master")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--family", default=None, help="analyze only this family key")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    inv = json.load(open(args.inventory))
    slugs = [r["slug"] for r in inv.get("rows", [])]
    if args.family:
        slugs = [s for s in slugs if family_key(s) == args.family]
    report = analyze(slugs, base=args.base, cwd=args.repo)
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
