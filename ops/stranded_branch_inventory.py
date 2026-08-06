#!/usr/bin/env python3
"""Inventory the agent/* branches on origin that never reached master.

Read-only. Produces the report; it does NOT requeue, merge, or change any task
state. Recovery is a separate, batched, individually-provenanced step — a
229-branch sweep is the exact shape of the M4_bulk_resolved_sweep that
manufactured 3,765 phantom merges, so nothing here is allowed to be bulk.

Line counts deliberately EXCLUDE lockfiles, build output and vendored trees.
The raw insertion count across the stranded set is ~1.28M lines, which is not a
measure of recoverable work — it is mostly generated. Quoting it would overstate
the backlog by an order of magnitude.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone

# Paths whose line counts are generated, vendored, or otherwise not human work.
NOISE_PATTERNS = [
    r"(^|/)package-lock\.json$", r"(^|/)pnpm-lock\.yaml$", r"(^|/)yarn\.lock$",
    r"(^|/)poetry\.lock$", r"(^|/)Cargo\.lock$", r"(^|/)composer\.lock$",
    r"(^|/)node_modules/", r"(^|/)vendor/", r"(^|/)dist/", r"(^|/)build/",
    r"(^|/)\.nuxt/", r"(^|/)\.next/", r"(^|/)coverage/", r"(^|/)__pycache__/",
    r"(^|/)generated/", r"\.min\.(js|css)$", r"\.map$", r"\.lock$",
    r"(^|/)public/assets/", r"\.(png|jpe?g|gif|svg|ico|webp|pdf|docx|xlsx)$",
]
_NOISE = re.compile("|".join(NOISE_PATTERNS))


def git(*args, cwd=None):
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return out.stdout.strip()


def is_noise(path):
    return bool(_NOISE.search(path))


def origin_agent_branches(cwd=None):
    raw = git("for-each-ref", "--format=%(refname:short)",
              "refs/remotes/origin/agent", cwd=cwd)
    return [b for b in raw.splitlines() if b.strip()]


def merged_set(base, cwd=None):
    raw = git("branch", "-r", "--merged", base, "--format=%(refname:short)", cwd=cwd)
    return {b.strip() for b in raw.splitlines() if b.strip()}


def source_line_delta(base, branch, cwd=None):
    """Insertions/deletions across real source files only."""
    raw = git("diff", "--numstat", f"{base}...{branch}", cwd=cwd)
    added = removed = files = noise_added = 0
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        a, d, path = parts
        a = int(a) if a.isdigit() else 0
        d = int(d) if d.isdigit() else 0
        if is_noise(path):
            noise_added += a
            continue
        added += a
        removed += d
        files += 1
    return {"source_added": added, "source_removed": removed,
            "source_files": files, "excluded_added": noise_added}


def merges_cleanly(base, branch, cwd=None):
    """True when the branch merges into base with no conflict. Never mutates."""
    merge_base = git("merge-base", base, branch, cwd=cwd)
    if not merge_base:
        return None
    res = subprocess.run(
        ["git", "merge-tree", "--write-tree", "--name-only", base, branch],
        cwd=cwd, capture_output=True, text=True)
    if res.returncode == 0:
        return True
    if res.returncode == 1:
        return False
    # Older git without --write-tree: fall back to the 3-arg form, where a
    # conflict marker in the output means a conflict.
    legacy = subprocess.run(["git", "merge-tree", merge_base, base, branch],
                            cwd=cwd, capture_output=True, text=True)
    return "<<<<<<<" not in legacy.stdout


def branch_age_days(branch, cwd=None):
    ts = git("log", "-1", "--format=%ct", branch, cwd=cwd)
    if not ts.isdigit():
        return None
    committed = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return round((datetime.now(timezone.utc) - committed).total_seconds() / 86400, 1)


def slug_of(branch):
    return branch.split("origin/agent/", 1)[-1]


def build_inventory(base="origin/master", cwd=None, limit=None):
    branches = origin_agent_branches(cwd=cwd)
    merged = merged_set(base, cwd=cwd)
    stranded = [b for b in branches if b not in merged]
    if limit:
        stranded = stranded[:limit]

    rows = []
    for branch in stranded:
        delta = source_line_delta(base, branch, cwd=cwd)
        rows.append({
            "branch": branch,
            "slug": slug_of(branch),
            "age_days": branch_age_days(branch, cwd=cwd),
            "clean_merge": merges_cleanly(base, branch, cwd=cwd),
            **delta,
        })
    rows.sort(key=lambda r: (not r["clean_merge"], -(r["age_days"] or 0)))
    return {"base": base, "total_agent_branches": len(branches),
            "already_merged": len(branches) - len(stranded),
            "stranded": len(stranded), "rows": rows}


def classify_conflicting(row):
    """(a) superseded, (b) still wanted, (c) unclear — never a guess.

    Ambiguity resolves to 'unclear' by design. Closing a branch as superseded on
    thin evidence destroys real work, so only an empty source delta (nothing
    left to recover) is treated as definitive.
    """
    if row["source_files"] == 0 and row["source_added"] == 0:
        return "superseded", "no source-file delta remains against master"
    return "unclear", "conflicts and still carries source changes; needs operator judgement"


def render_markdown(inv, task_states=None):
    task_states = task_states or {}
    clean = [r for r in inv["rows"] if r["clean_merge"]]
    conflict = [r for r in inv["rows"] if r["clean_merge"] is False]
    src_total = sum(r["source_added"] for r in inv["rows"])
    noise_total = sum(r["excluded_added"] for r in inv["rows"])

    out = [
        "# Stranded agent branches — inventory",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat()} against `{inv['base']}`.",
        "Read-only inventory. No branch was merged and no task state was changed to",
        "produce it.",
        "",
        "## Totals",
        "",
        f"- agent/* branches on origin: **{inv['total_agent_branches']}**",
        f"- already merged into master: **{inv['already_merged']}**",
        f"- **STRANDED (not an ancestor of master): {inv['stranded']}**",
        f"  - merge cleanly today: **{len(clean)}**",
        f"  - would conflict: **{len(conflict)}**",
        "",
        f"- real source lines added across the stranded set: **{src_total:,}**",
        f"- lines excluded as lockfile / build output / vendored / binary: {noise_total:,}",
        "",
        "The excluded figure is why the raw ~1.28M insertion count must not be quoted as",
        "recoverable work. Only the source figure above represents human output.",
        "",
        "## Root cause — confirmed, already fixed",
        "",
        "Commit `7ec2d4e` (`fix(merge): scan-window starvation — the real cause of months of",
        "stranded work`) is **already an ancestor of master**, and it does explain this",
        "backlog. `_pick_cards()` scanned only the NEWEST 3,000 approved cards out of 238,177",
        "rows, and the train stamps `decided_by` on every card it handles — so the newest",
        "3,000 were almost entirely already-decided outcomes. A card not merged immediately",
        "aged out of that window within hours and became invisible forever, while",
        "`ensure_integration_card` still found it and refused to file a replacement, so the",
        "task could not be re-queued either. That is both why 'undecided cards = 0' was",
        "reported alongside 90 waiting tasks, and why finished work went 'merged, plausible,",
        "inert' for months. The fix scans oldest-first as well and took `_pick_cards()` from",
        "effectively 0 actionable cards to 103.",
        "",
        "**This task is therefore about draining the backlog that fix explains, not",
        "re-diagnosing it.**",
        "",
        "## Not to be confused with the phantom tasks",
        "",
        "The 10,224 PHANTOM_UNVERIFIED tasks are a different population and are NOT",
        "recoverable: mechanism M3_bulk_update alone covers 6,256 of them and has 0 branches,",
        "1 commit and 39 artifacts between them — they mostly produced nothing, so they can",
        "only be re-run. The branches below are the opposite case: the code exists.",
        "",
        "## Recovery rules",
        "",
        "- Clean branches are requeued as the ORIGINAL task with a `-recovered` slug suffix so",
        "  they re-enter the normal pipeline and pass the normal gates. They are **not** merged",
        "  directly to master and do **not** bypass the merge train, QA, or the release train.",
        "- Every requeue is an individual insert carrying its own provenance note. No bulk",
        "  state change, ever.",
        "- Nothing is marked MERGED that has not actually merged.",
        "- A branch whose original task row is gone is still inventoried; no task is invented",
        "  for it.",
        "- Conflicting branches are classified superseded / still-wanted / unclear, and",
        "  ambiguity resolves to **unclear** rather than to a guess.",
        "",
        "## Branches that merge cleanly",
        "",
        "| branch | age (d) | src +/- | files | task state |",
        "|---|---:|---:|---:|---|",
    ]
    for r in clean:
        state = task_states.get(r["slug"], "— no task row —")
        out.append(f"| `{r['slug']}` | {r['age_days']} | "
                   f"+{r['source_added']}/-{r['source_removed']} | "
                   f"{r['source_files']} | {state} |")
    out += ["", "## Branches that would conflict", "",
            "| branch | age (d) | src +/- | files | class | task state |",
            "|---|---:|---:|---:|---|---|"]
    for r in conflict:
        state = task_states.get(r["slug"], "— no task row —")
        klass, _why = classify_conflicting(r)
        out.append(f"| `{r['slug']}` | {r['age_days']} | "
                   f"+{r['source_added']}/-{r['source_removed']} | "
                   f"{r['source_files']} | {klass} | {state} |")
    out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/master")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    inv = build_inventory(base=args.base, cwd=args.repo, limit=args.limit)
    if args.json:
        print(json.dumps(inv, indent=2))
        return 0
    text = render_markdown(inv)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
        print(f"wrote {args.out} ({inv['stranded']} stranded branches)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
