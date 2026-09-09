"""
reconcile_stranded_branches.py — branch-driven recovery for stranded agent/* work.

WHY THIS EXISTS (and why backfill_stranded_cards.py is not enough)
    backfill_stranded_cards.py starts from the TASKS table: DONE tasks that carry an
    artifact_branch but hold no live merge card. That closes the DONE-before-card hole,
    but it is blind to the larger population measured during the 2026-08-06 stranded
    branch audit: 482 agent/* branches on origin, 363 already merged into master, 119
    genuinely stranded (103 clean-mergeable, 16 conflicting).

    A branch goes stranded and stays invisible to the task-driven backfill whenever:
      - the task never reached DONE (executor crashed after push, marked BLOCKED, or the
        row was requeued and later superseded),
      - the task reached DONE but artifact_branch was never written back,
      - the task row is gone entirely (project re-registered, slug rewritten),
      - the branch was pushed by a path that files no task at all (hotfix, bridge, manual).

    In every one of those cases the WORK EXISTS ON ORIGIN and nothing will ever look at it.
    The only reliable source of truth for "what has been pushed" is origin itself, so this
    reconciler enumerates branches first and consults the database second — the mirror
    image of backfill_stranded_cards.py, deliberately.

WHAT THIS DOES
    1. Lists agent/* heads on origin (git ls-remote — no fetch, no checkout, no worktree).
    2. Drops every branch already merged into the base (git merge-base --is-ancestor).
    3. Classifies the remainder as CLEAN or CONFLICTING (git merge-tree, read-only).
    4. Files an approved integration card for the CLEAN ones so the merge train can see
       them. Conflicting branches are reported, never auto-carded — a conflicting branch
       needs a rebase decision, and filing a card only moves the strand into the train.

WHAT THIS DELIBERATELY DOES NOT DO
    - It never writes to `tasks`. Not one UPDATE. Like the card backfill, this repairs
      missing derived rows only; keeping it read-only against `tasks` is what makes it
      safe to re-run at any time.
    - It never merges, pushes, rebases or deletes a branch. Classification is read-only.
    - It never files a card for a conflicting branch (see above).
    - It never files a card for a slug that already has one (re-checked per slug
      immediately before each insert).

SAFETY PROPERTIES
    - report-only unless --apply is passed.
    - idempotent: existence re-checked per slug at write time, so a second run is a no-op.
    - checkpointed: an interrupted run resumes instead of restarting.
    - fail-soft: every git call that errors classifies the branch as UNKNOWN and is
      skipped, never carded. Fail CLOSED — an unclassifiable branch is not queued.

Usage:
    python3 reconcile_stranded_branches.py                          # report only
    python3 reconcile_stranded_branches.py --project beethoven      # one project
    python3 reconcile_stranded_branches.py --apply                  # file cards for CLEAN
    python3 reconcile_stranded_branches.py --apply --limit 200 --batch 25
"""
import argparse
import bisect
import json
import os
import subprocess
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

import db  # noqa: E402
import merge_train  # noqa: E402

BRANCH_PREFIX = os.environ.get("ORCH_AGENT_BRANCH_PREFIX", "agent/")
GIT_TIMEOUT = int(os.environ.get("ORCH_RECONCILE_GIT_TIMEOUT", "120"))

CHECKPOINT = os.path.join(
    os.environ.get("CLAUDE_ORCH_HOME",
                   os.path.join(os.path.dirname(_DIR), ".runtime")),
    "reconcile-stranded-branches.checkpoint.json")

PROVENANCE = ("reconcile_stranded_branches: branch exists on origin, is not an ancestor "
              "of the base branch and merges cleanly, but held no integration card — the "
              "task-driven backfill could not see it because no DONE task carried this "
              "branch. Reconciled from origin.")

CLEAN, CONFLICTING, MERGED, UNKNOWN = "clean", "conflicting", "merged", "unknown"


# ── checkpoint ────────────────────────────────────────────────────────────────

def _load_checkpoint():
    try:
        with open(CHECKPOINT) as f:
            return set(json.load(f).get("done_branches") or [])
    except Exception:
        return set()


def _load_cursors():
    """project -> the branch name the last scan stopped after. {} on any failure.

    Separate from `done_branches`, which records branches that were CARDED. That set
    can never advance the scan window past a branch that is merged, conflicting, or
    unknown, because those are never added to it — so it cannot be used as a cursor.
    """
    try:
        with open(CHECKPOINT) as f:
            return dict(json.load(f).get("scan_cursors") or {})
    except Exception:
        return {}


def _save_checkpoint(done_branches, scan_cursors=None):
    try:
        os.makedirs(os.path.dirname(CHECKPOINT), exist_ok=True)
        payload = {"done_branches": sorted(done_branches)}
        # Preserve whichever half of the file this caller is not writing.
        payload["scan_cursors"] = dict(_load_cursors() if scan_cursors is None
                                       else scan_cursors)
        with open(CHECKPOINT, "w") as f:
            json.dump(payload, f)
    except Exception as e:
        print(f"[checkpoint] could not persist: {e}")


def select_window(branch_names, limit, start_after=""):
    """The next `limit` branches to scan, rotating from `start_after`.

    THE WINDOW HAS TO MOVE OR THE TAIL IS INVISIBLE FOREVER.
    -------------------------------------------------------
    `inventory` used `sorted(heads.items())[:limit]`, which is the alphabetically FIRST
    `limit` branches — the identical set on every run. Measured on beethoven 2026-09-09:
    1,618 agent/* branches on origin against the default limit of 500, so roughly 1,118
    branches (69%) could never be classified, never be carded, and would stay stranded
    no matter how often the reconciler ran.

    That is the same scan-window starvation this tool exists to remedy: the parent
    task's confirmed root cause was `_pick_cards()` scanning only the newest 3,000 of
    238,177 approved cards. Reproducing it here made the recovery path blind in exactly
    the way the thing it recovers from was blind.

    Rotating instead of truncating means the population is covered in ceil(n/limit)
    runs and no branch is structurally excluded. Wrapping (rather than stopping at the
    end) keeps coverage cyclical, so branches near the start are re-examined too — a
    branch that was CONFLICTING last month may merge cleanly today.
    """
    ordered = sorted(branch_names)
    if not ordered:
        return []
    start = 0
    if start_after:
        # bisect_right: resume strictly AFTER the cursor, and tolerate a cursor whose
        # branch has since been deleted (it lands at the right insertion point anyway).
        start = bisect.bisect_right(ordered, start_after)
        if start >= len(ordered):
            start = 0
    if limit is None or limit <= 0 or limit >= len(ordered):
        return ordered[start:] + ordered[:start]
    window = ordered[start:start + limit]
    if len(window) < limit:
        window += ordered[:limit - len(window)]
    return window


# ── git (all read-only) ───────────────────────────────────────────────────────

def _git(repo_path, *args, timeout=None):
    """Run a git command. Returns (rc, stdout) — never raises."""
    try:
        r = subprocess.run(["git", *args], cwd=repo_path, capture_output=True,
                           text=True, timeout=timeout or GIT_TIMEOUT)
        return r.returncode, (r.stdout or "")
    except Exception:
        return 1, ""


def list_agent_branches(repo_path, prefix=BRANCH_PREFIX):
    """agent/* heads on origin, as {branch: sha}. Empty dict on any failure."""
    if not repo_path or not os.path.isdir(repo_path):
        return {}
    rc, out = _git(repo_path, "ls-remote", "--heads", "origin", f"{prefix}*")
    if rc != 0:
        return {}
    heads = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        sha, ref = parts
        if ref.startswith("refs/heads/"):
            heads[ref[len("refs/heads/"):]] = sha
    return heads


def _base_sha(repo_path, base_branch):
    """Resolve the base branch, preferring the remote-tracking ref."""
    for ref in (f"origin/{base_branch}", base_branch):
        rc, out = _git(repo_path, "rev-parse", "--verify", "--quiet", ref)
        if rc == 0 and out.strip():
            return out.strip()
    return ""


def classify_branch(repo_path, branch_sha, base_sha):
    """MERGED / CLEAN / CONFLICTING / UNKNOWN for one branch head.

    Read-only: merge-base and merge-tree never touch the working tree, so this is safe
    to run against the live checkout while agents are working in it.
    """
    if not branch_sha or not base_sha:
        return UNKNOWN
    rc, _ = _git(repo_path, "merge-base", "--is-ancestor", branch_sha, base_sha)
    if rc == 0:
        return MERGED
    # git merge-tree --write-tree exits non-zero on conflict (git >= 2.38). Older git
    # has no such exit contract, so fall back to scanning for conflict markers in the
    # 3-way form's output. Anything we cannot read confidently stays UNKNOWN.
    rc, out = _git(repo_path, "merge-tree", "--write-tree", "--name-only",
                   base_sha, branch_sha)
    if rc == 0:
        return CLEAN
    if rc == 1:
        return CONFLICTING
    rc2, out2 = _git(repo_path, "merge-tree", base_sha, base_sha, branch_sha)
    if rc2 != 0:
        return UNKNOWN
    return CONFLICTING if "<<<<<<<" in out2 else CLEAN


def slug_for_branch(branch, prefix=BRANCH_PREFIX):
    return branch[len(prefix):] if branch.startswith(prefix) else branch


# ── inventory ─────────────────────────────────────────────────────────────────

def inventory(project, limit=500, start_after=""):
    """Classify a rotating window of one project's agent/* branches.

    Returns {"project", "total", "scanned", "cursor", "merged", "clean",
             "conflicting", "unknown", "branches": [...]}.

    `total` is the whole population; `scanned` is how many of them this run actually
    classified. They were previously conflated — `total` reported 1,618 while the
    counts beside it described 500 — so a report that had seen less than a third of the
    branches read as if it had seen all of them. Two names, because the gap between
    them is the thing an operator needs to notice.
    """
    name = project.get("name") or str(project.get("id"))
    repo_path = project.get("repo_path")
    base_branch = project.get("default_base") or "master"
    out = {"project": name, "repo_path": repo_path, "base": base_branch,
           "total": 0, "scanned": 0, "cursor": start_after,
           "merged": 0, "clean": 0, "conflicting": 0, "unknown": 0,
           "branches": []}
    if not repo_path or not os.path.isdir(repo_path):
        return out

    base_sha = _base_sha(repo_path, base_branch)
    heads = list_agent_branches(repo_path)
    out["total"] = len(heads)

    window = select_window(list(heads), limit, start_after=start_after)
    out["scanned"] = len(window)
    out["cursor"] = window[-1] if window else start_after

    for branch in window:
        sha = heads[branch]
        status = classify_branch(repo_path, sha, base_sha)
        out[status] = out.get(status, 0) + 1
        if status != CLEAN:
            # Only clean branches are candidates; the rest are counted, not inspected
            # further (a card lookup per branch across 482 branches is pure overhead).
            out["branches"].append({"branch": branch, "sha": sha, "status": status,
                                    "slug": slug_for_branch(branch), "has_card": None})
            continue
        slug = slug_for_branch(branch)
        has_card = False
        try:
            has_card = bool(merge_train._find_existing_card(slug))
        except Exception:
            # Fail CLOSED: if we cannot prove a card is absent, assume it is present.
            has_card = True
        out["branches"].append({"branch": branch, "sha": sha, "status": status,
                                "slug": slug, "has_card": has_card})
    return out


def stranded_from(inv):
    """Clean, un-carded branches — the only ones this tool will queue."""
    return [b for b in inv.get("branches") or []
            if b.get("status") == CLEAN and b.get("has_card") is False]


# ── run ───────────────────────────────────────────────────────────────────────

def run(project_name=None, limit=500, batch=25, apply=False):
    projects = db.select("projects") or []
    if project_name:
        projects = [p for p in projects if p.get("name") == project_name]
    if not projects:
        print(f"reconcile_stranded_branches: no matching project ({project_name!r})")
        return {"projects": 0, "stranded": 0, "filed": 0, "failed": 0, "applied": apply}

    already = _load_checkpoint()
    processed = set(already)
    cursors = _load_cursors()
    totals = {"projects": 0, "branches": 0, "scanned": 0, "merged": 0, "clean": 0,
              "conflicting": 0, "unknown": 0, "stranded": 0, "filed": 0,
              "failed": 0, "applied": apply}

    for proj in projects:
        pname = proj.get("name") or str(proj.get("id"))
        inv = inventory(proj, limit=limit, start_after=cursors.get(pname, ""))
        if not inv["total"]:
            continue
        # Advance the cursor even when nothing was filed. The window has to move on
        # scan, not on success, or a stretch of merged/conflicting branches parks it
        # and the tail goes unseen again.
        if inv.get("cursor"):
            cursors[pname] = inv["cursor"]
        totals["projects"] += 1
        for k in ("merged", "clean", "conflicting", "unknown"):
            totals[k] += inv.get(k, 0)
        totals["branches"] += inv["total"]
        totals["scanned"] += inv.get("scanned", inv["total"])

        stranded = stranded_from(inv)
        todo = [b for b in stranded if b["branch"] not in already]
        totals["stranded"] += len(stranded)
        # `.get` with a total default: an inventory supplied by a caller (or a test
        # stub) that predates the coverage fields still reports coherently, as
        # "everything was scanned", which is what it meant before the fields existed.
        scanned = inv.get("scanned", inv["total"])
        coverage = ("" if scanned >= inv["total"] else
                    f" — {inv['total'] - scanned} not scanned this pass; "
                    f"resume after {inv.get('cursor', '')!r}")
        print(f"[{inv['project']}] {scanned} of {inv['total']} agent branches "
              f"scanned{coverage} — {inv['merged']} merged, {inv['clean']} clean, "
              f"{inv['conflicting']} conflicting, {inv['unknown']} unknown; "
              f"{len(stranded)} clean+uncarded ({len(stranded) - len(todo)} done earlier)")

        for i in range(0, len(todo), batch):
            for b in todo[i:i + batch]:
                if not apply:
                    print(f"  would file card: {inv['project']}/{b['slug']} [{b['branch']}]")
                    totals["filed"] += 1
                    continue
                # Re-check immediately before writing — a concurrent executor or the
                # task-driven backfill may have filed this card since inventory() ran.
                try:
                    if merge_train._find_existing_card(b["slug"]):
                        processed.add(b["branch"])
                        continue
                    state = merge_train.ensure_integration_card_result(
                        inv["project"], b["slug"],
                        kind="integrate",
                        title=f"merge of {b['slug']}",
                        why=PROVENANCE,
                        detail=(f"branch={b['branch']} sha={b['sha'][:12]} "
                                f"base={inv['base']} reconciled by "
                                f"reconcile_stranded_branches.py"),
                        status="approved",
                        decided_by="canonical-train:reconcile-stranded-branches",
                    )
                except Exception as e:
                    state = f"error:{e}"
                if state in merge_train.CARD_OK:
                    totals["filed"] += 1
                    processed.add(b["branch"])
                    print(f"  filed: {inv['project']}/{b['slug']} [{b['branch']}] ({state})")
                else:
                    totals["failed"] += 1
                    print(f"  FAILED: {inv['project']}/{b['slug']} [{b['branch']}] ({state})")
            if apply:
                _save_checkpoint(processed, scan_cursors=cursors)

    # Persist the cursor even on a report-only run. Scanning is what the cursor tracks,
    # and a --apply-less pass scans exactly as much as an --apply one; parking the
    # cursor behind `apply` would leave the default invocation re-reading the same
    # window forever, which is the bug this is fixing.
    if apply or cursors:
        _save_checkpoint(processed, scan_cursors=cursors)

    print(f"reconcile_stranded_branches: {totals}")
    return totals


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--project", default=None, help="limit to one project by name")
    ap.add_argument("--limit", type=int, default=500, help="max branches per project")
    ap.add_argument("--batch", type=int, default=25)
    ap.add_argument("--apply", action="store_true",
                    help="actually file cards for clean, uncarded branches "
                         "(default: report only)")
    args = ap.parse_args()
    run(project_name=args.project, limit=args.limit, batch=args.batch, apply=args.apply)


if __name__ == "__main__":
    main()
