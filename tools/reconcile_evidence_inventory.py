#!/usr/bin/env python3
"""reconcile_evidence_inventory.py — one manifest of every piece of evidence, all classified.

WHY. Reconciliation evidence arrives from four different places — git stashes, registered
worktrees, refs/orch-rescue/* snapshots, and loose files — and each previous pass
enumerated a different subset by hand. Two runs over the same repo produced different
totals, so "did we look at everything?" was unanswerable, and an item nobody enumerated
was indistinguishable from an item that was examined and found empty.

This produces ONE machine-readable manifest covering all four sources, and classifies
every entry. UNKNOWN is not an allowed resting state: `--strict` exits non-zero if any
item is unclassified, because an unexamined item that looks like a clean report is the
failure the coverage doctrine exists to prevent.

READ-ONLY, ABSOLUTELY. Nothing here deletes, resets, cleans, pops, moves, prunes or
checks out. Every git call is an inspection (`stash list`, `worktree list`, `for-each-ref`,
`show`, `log`, `merge-base`, `diff --stat`). The evidence must survive being looked at.

    python3 tools/reconcile_evidence_inventory.py                       # human summary
    python3 tools/reconcile_evidence_inventory.py --json                # manifest to stdout
    python3 tools/reconcile_evidence_inventory.py --out evidence_manifest.json
    python3 tools/reconcile_evidence_inventory.py --strict              # exit 1 on UNKNOWN
"""
import argparse
import json
import os
import subprocess
import sys

REPO = os.environ.get("ORCH_REPO_PATH", os.getcwd())
BASE = os.environ.get("ORCH_BASE_REF", "origin/master")
GIT_TIMEOUT = int(os.environ.get("ORCH_GIT_TIMEOUT_SECONDS", "120"))

ALREADY_PRESENT = "ALREADY_PRESENT"
SUPERSEDED_BY_NEWER = "SUPERSEDED_BY_NEWER"
ACTIVE_IN_ANOTHER_TASK = "ACTIVE_IN_ANOTHER_TASK"
RECOVERABLE_VALUE = "RECOVERABLE_VALUE"
CONFLICTED = "CONFLICTED_NEEDS_FOCUSED_TASK"
UNKNOWN = "UNKNOWN"

#: Vocabulary shared with tools/reconcile_rescue_refs.py and
#: server/utils/reconcile/reconcileAgentBranches.ts. One taxonomy, three implementations —
#: they must not drift.
CLASSIFICATIONS = (ALREADY_PRESENT, SUPERSEDED_BY_NEWER, ACTIVE_IN_ANOTHER_TASK,
                   RECOVERABLE_VALUE, CONFLICTED)

#: Build/scratch output that a sweep captures but which is never source value.
NOISE_HINTS = ("/node_modules/", "/.nuxt/", "/dist/", "/.output/", "/coverage/",
               "/__pycache__/", ".pyc", "/.orch/", ".recovery-intent-", "/.DS_Store")


def git(*args, cwd=None):
    """Read-only git call. Returns stdout, or "" on any failure."""
    try:
        r = subprocess.run(["git", "-C", cwd or REPO, *args],
                           capture_output=True, text=True, errors="replace",
                           timeout=GIT_TIMEOUT)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def is_noise(path):
    p = "/" + str(path or "").replace(os.sep, "/")
    return any(h in p for h in NOISE_HINTS)


def signal_paths(paths):
    """Paths that represent real source value, with build/scratch noise removed."""
    return [p for p in (paths or []) if p and not is_noise(p)]


# ── enumeration: four sources, one shape ────────────────────────────────────────

def enumerate_stashes():
    out = []
    for line in git("stash", "list", "--format=%gd%x09%H%x09%gs").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            out.append({"source": parts[0], "type": "stash", "sha": parts[1],
                        "subject": parts[2] if len(parts) > 2 else ""})
    return out


def enumerate_worktrees():
    out = []
    current = {}
    for line in git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            if current:
                out.append(current)
            current = {"source": line[len("worktree "):].strip(), "type": "worktree"}
        elif line.startswith("HEAD "):
            current["sha"] = line[len("HEAD "):].strip()
        elif line.startswith("branch "):
            current["subject"] = line[len("branch "):].strip()
    if current:
        out.append(current)
    # The first entry is the main checkout; it is not recovery evidence.
    return out[1:]


def enumerate_rescue_refs():
    out = []
    fmt = "%(refname)%09%(objectname)%09%(contents:subject)"
    for line in git("for-each-ref", "--format=" + fmt, "refs/orch-rescue/").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            out.append({"source": parts[0], "type": "rescue ref", "sha": parts[1],
                        "subject": parts[2] if len(parts) > 2 else ""})
    return out


def enumerate_files(paths):
    out = []
    for path in paths or []:
        if not path:
            continue
        try:
            size = os.path.getsize(path) if os.path.isfile(path) else None
        except OSError:
            size = None
        out.append({"source": path, "type": "file", "sha": "",
                    "subject": os.path.basename(path), "size": size})
    return out


def inventory(extra_files=None):
    """Every evidence item from every source, unclassified. Read-only."""
    items = []
    for fn in (enumerate_stashes, enumerate_worktrees, enumerate_rescue_refs):
        try:
            items.extend(fn())
        except Exception as exc:
            items.append({"source": f"<{fn.__name__} failed>", "type": "error",
                          "sha": "", "subject": str(exc)[:200]})
    items.extend(enumerate_files(extra_files))
    for it in items:
        it.setdefault("sha", "")
        it.setdefault("subject", "")
        it["classification"] = UNKNOWN
        it["reason"] = ""
    return items


# ── classification ─────────────────────────────────────────────────────────────

def is_ancestor(sha, of=None):
    if not sha:
        return False
    try:
        return subprocess.run(
            ["git", "-C", REPO, "merge-base", "--is-ancestor", sha, of or BASE],
            capture_output=True, timeout=GIT_TIMEOUT).returncode == 0
    except Exception:
        return False


def added_paths(sha):
    """Paths the commit adds relative to its merge-base with BASE."""
    if not sha:
        return []
    mb = git("merge-base", BASE, sha)
    if not mb:
        return []
    out = git("diff", "--name-only", "--diff-filter=A", f"{mb}..{sha}")
    return [p for p in out.splitlines() if p.strip()]


def absent_from_base(paths):
    """Of `paths`, those BASE does not have."""
    if not paths:
        return []
    have = set(git("ls-tree", "-r", "--name-only", BASE).splitlines())
    return [p for p in paths if p not in have]


def classify(item, live_slugs=None):
    """Assign one of CLASSIFICATIONS. Never leaves UNKNOWN silently.

    ACTIVE_IN_ANOTHER_TASK is decided from the live task list the caller passes in
    (read-only); a worktree or ref whose slug is held by a running task must not be
    presented as recoverable, because "recovering" it races a live agent.
    """
    try:
        source = str(item.get("source") or "")
        sha = str(item.get("sha") or "")

        if live_slugs:
            for slug in live_slugs:
                if slug and slug in source:
                    item["classification"] = ACTIVE_IN_ANOTHER_TASK
                    item["reason"] = f"a live task ({slug}) holds this; do not duplicate it"
                    return item

        if item.get("type") == "worktree" and not os.path.isdir(source):
            item["classification"] = CONFLICTED
            item["reason"] = "worktree directory is gone; nothing uncommitted can be read"
            return item

        if sha and is_ancestor(sha):
            item["classification"] = ALREADY_PRESENT
            item["reason"] = f"reachable from {BASE}; its work is in merged history"
            return item

        if sha:
            adds = signal_paths(absent_from_base(added_paths(sha)))
            if adds:
                item["classification"] = RECOVERABLE_VALUE
                item["reason"] = (f"{len(adds)} source path(s) absent from {BASE} "
                                  f"(e.g. {', '.join(adds[:3])})")
                item["paths"] = adds[:50]
                return item
            item["classification"] = SUPERSEDED_BY_NEWER
            item["reason"] = (f"adds no source path {BASE} lacks; the base carries an "
                              f"equal or newer implementation")
            return item

        # No sha to reason about — a loose file, or a ref that would not resolve.
        item["classification"] = CONFLICTED
        item["reason"] = "no resolvable commit; needs a focused look rather than a guess"
        return item
    except Exception as exc:
        # Escalate rather than drop: an item we could not judge is exactly the UNKNOWN the
        # coverage doctrine forbids, so it becomes a focused task instead.
        item["classification"] = CONFLICTED
        item["reason"] = f"classification failed ({str(exc)[:120]}); escalated, not dropped"
        return item


def live_task_slugs():
    """Slugs of tasks currently RUNNING. Read-only; empty on any failure."""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "runner"))
        import db
        rows = db.select("tasks", {"select": "slug", "state": "eq.RUNNING",
                                   "limit": "5000"}) or []
        return {r.get("slug") for r in rows if r.get("slug")}
    except Exception:
        return set()


def build_manifest(extra_files=None, live_slugs=None):
    slugs = live_task_slugs() if live_slugs is None else live_slugs
    items = [classify(it, slugs) for it in inventory(extra_files)]
    counts = {}
    for it in items:
        counts[it["classification"]] = counts.get(it["classification"], 0) + 1
    return {
        "base": BASE,
        "base_sha": git("rev-parse", BASE),
        "total": len(items),
        "counts": counts,
        "unknown": counts.get(UNKNOWN, 0),
        "items": items,
    }


def render(manifest):
    lines = [f"{manifest['total']} evidence item(s) vs {manifest['base']}"]
    for name in CLASSIFICATIONS + (UNKNOWN,):
        n = manifest["counts"].get(name, 0)
        if n:
            lines.append(f"  {name:<32} {n}")
    if manifest["unknown"]:
        lines.append(f"\n{manifest['unknown']} item(s) UNKNOWN — every item must be classified")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("files", nargs="*", help="extra evidence file paths to include")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default="", help="write the manifest to this path")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any item is UNKNOWN")
    args = ap.parse_args(argv)

    manifest = build_manifest(args.files)
    print(json.dumps(manifest, indent=2) if args.json else render(manifest))

    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, indent=2)
                fh.write("\n")
        except Exception as exc:
            print(f"manifest write failed ({args.out}): {exc}", file=sys.stderr)

    return 1 if (args.strict and manifest["unknown"]) else 0


if __name__ == "__main__":
    sys.exit(main())
