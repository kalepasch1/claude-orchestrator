#!/usr/bin/env python3
"""merge_truth.py — MERGED must mean the commit reached the production branch.

## Why this exists

Measured 2026-08-06 over 24 beethoven tasks in MERGED with a non-null artifact_commit,
each SHA checked with `git merge-base --is-ancestor <sha> origin/master`:

    in master ................................  4  (17%)
    MERGED but commit NOT an ancestor of master 10  (42%)
    commit does not exist on origin at all .... 10  (42%)

83% of recent MERGED rows were false, and 20 of the phantoms were created AFTER the
2026-08-04 audit — so the writer is live, not historical.

The 2026-08-04 remediation made merges record an `artifact_commit`, and the column is now
populated 218/218 and 169/169. That was read as proof the fix held. It is not. Populating a
column proves a string was written; it does not prove the commit exists, nor that it reached
the production branch. **The check must be reachability, never presence.**

## The gate

`verify_merge_reachable()` returns one of three verdicts, and the third is what makes this
safe to deploy:

    ok           artifact_commit is non-empty, the object exists, and it is an ancestor of
                 the project's prod_branch. MERGED may be written.
    phantom      one of those checks answered NO. Write PHANTOM_UNVERIFIED instead, with a
                 note naming which check failed and the SHA.
    infra_error  git itself could not answer (network down, fetch timeout, repo missing or
                 corrupt). Change NOTHING and log. A fetch timeout must never flip a real
                 merge to PHANTOM_UNVERIFIED — that is the mirror-image failure and just as
                 damaging as the phantom it is trying to catch.

Callers route their MERGED writes through `gate_merged_patch()`, which returns the patch to
apply, or None meaning "write nothing this cycle".

## Reconciler

`reconcile()` is read-only by construction: it reports how many MERGED rows are real without
trusting the writer, and mutates nothing. Operators run it directly:

    python3 runner/merge_truth.py                 # all projects
    python3 runner/merge_truth.py --project beethoven --limit 200
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402

# Verdicts
OK = "ok"
PHANTOM = "phantom"
INFRA_ERROR = "infra_error"

# The state that makes a blocked merge visible instead of silently absent.
PHANTOM_STATE = "PHANTOM_UNVERIFIED"

ALARM_GATE = "merge_truth"
ALARM_KIND = "phantom_merge_blocked"

# Dedupe window for alarms, so a systemic outage files one row rather than thousands.
ALARM_DEDUPE_HOURS = int(os.environ.get("ORCH_MERGE_TRUTH_ALARM_DEDUPE_H", "6") or 6)

_FETCH_TIMEOUT_S = int(os.environ.get("ORCH_MERGE_TRUTH_FETCH_TIMEOUT_S", "60") or 60)
_GIT_TIMEOUT_S = int(os.environ.get("ORCH_MERGE_TRUTH_GIT_TIMEOUT_S", "30") or 30)

# Only re-fetch a given (repo, branch) this often. The reconciler walks hundreds of tasks and
# would otherwise fetch once per task.
_FETCH_TTL_S = int(os.environ.get("ORCH_MERGE_TRUTH_FETCH_TTL_S", "120") or 120)
_fetched: dict = {}


def _git(repo, *args, timeout=None):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          timeout=timeout or _GIT_TIMEOUT_S)


def _fetch(repo, branch):
    """Refresh origin/<branch>. Returns None on success, else an error string.

    Rule 4: a commit absent locally but present on origin must not read as missing. So a
    failed fetch is an infra error, never evidence of a phantom.
    """
    key = (repo, branch)
    now = time.time()
    last = _fetched.get(key)
    if last and now - last < _FETCH_TTL_S:
        return None
    try:
        r = _git(repo, "fetch", "origin", branch, timeout=_FETCH_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return f"fetch origin {branch} timed out after {_FETCH_TIMEOUT_S}s"
    except OSError as exc:
        return f"fetch origin {branch} failed: {exc}"
    if r.returncode:
        return f"fetch origin {branch} failed: {(r.stderr or '').strip()[-160:]}"
    _fetched[key] = now
    return None


def invalidate_fetch_cache():
    """Drop the fetch TTL cache (tests, and long-running processes that must re-check)."""
    _fetched.clear()


def _resolve_prod_ref(repo, prod_branch):
    """Prefer origin/<prod_branch>; fall back to the local ref if origin is not present.

    Returns (ref, err). A repo with neither is an infra error, not a phantom: it means we
    cannot ask the question, not that the answer is no.
    """
    for ref in (f"origin/{prod_branch}", prod_branch):
        try:
            r = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        except (subprocess.TimeoutExpired, OSError) as exc:
            return None, f"rev-parse {ref} failed: {exc}"
        if r.returncode == 0:
            return ref, None
    return None, f"neither origin/{prod_branch} nor {prod_branch} resolves in {repo}"


def verify_merge_reachable(repo, sha, prod_branch, fetch=True):
    """Is `sha` really on `prod_branch`? Returns (verdict, reason).

    Deliberately three-valued. Collapsing infra_error into phantom is what would let a
    network blip mass-reclassify real merges.
    """
    sha = (sha or "").strip()
    if not sha:
        return PHANTOM, "artifact_commit is empty"
    if not prod_branch:
        return INFRA_ERROR, "project has no prod_branch configured"
    if not repo or not os.path.isdir(repo):
        return INFRA_ERROR, f"repo path missing: {repo!r}"

    if fetch:
        err = _fetch(repo, prod_branch)
        if err:
            return INFRA_ERROR, err

    # Does the object exist at all?
    try:
        exists = _git(repo, "cat-file", "-e", f"{sha}^{{commit}}")
    except (subprocess.TimeoutExpired, OSError) as exc:
        return INFRA_ERROR, f"cat-file failed: {exc}"
    if exists.returncode != 0:
        return PHANTOM, f"commit {sha[:12]} does not exist in {repo}"

    ref, err = _resolve_prod_ref(repo, prod_branch)
    if err:
        return INFRA_ERROR, err

    try:
        anc = _git(repo, "merge-base", "--is-ancestor", sha, ref)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return INFRA_ERROR, f"merge-base failed: {exc}"
    if anc.returncode == 0:
        return OK, f"{sha[:12]} is an ancestor of {ref}"
    if anc.returncode == 1:
        return PHANTOM, f"commit {sha[:12]} is not an ancestor of {ref}"
    # Any other exit code is git failing to answer, not answering "no".
    return INFRA_ERROR, f"merge-base exit {anc.returncode}: {(anc.stderr or '').strip()[-160:]}"


def _project_row(project_id):
    try:
        rows = db.select("projects", {
            "select": "id,name,repo_path,prod_branch,default_base",
            "id": f"eq.{project_id}",
        }) or []
        return rows[0] if rows else None
    except Exception:
        return None


def resolve_target(task, repo=None, prod_branch=None):
    """Resolve (repo, prod_branch) for a task, preferring explicit args.

    prod_branch falls back to default_base — never to a hardcoded 'main'. Hardcoding is how a
    master-branch project gets measured against a branch it does not have.
    """
    if repo and prod_branch:
        return repo, prod_branch, None
    row = _project_row(task.get("project_id"))
    if not row:
        return repo, prod_branch, f"project {task.get('project_id')!r} not resolvable"
    return (repo or row.get("repo_path"),
            prod_branch or row.get("prod_branch") or row.get("default_base"),
            None)


def _hours_ago_iso(hours):
    import datetime as _dt
    return (_dt.datetime.now(_dt.timezone.utc)
            - _dt.timedelta(hours=hours)).isoformat()


def raise_phantom_alarm(task, sha, reason, dedupe_hours=None):
    """One deduped orch_gate_alarms row. Fail-soft: alarming must never break the caller."""
    hours = ALARM_DEDUPE_HOURS if dedupe_hours is None else dedupe_hours
    try:
        recent = db.select("orch_gate_alarms", {
            "select": "id",
            "gate": f"eq.{ALARM_GATE}",
            "kind": f"eq.{ALARM_KIND}",
            "resolved_at": "is.null",
            "created_at": f"gte.{_hours_ago_iso(hours)}",
            "limit": "1",
        }) or []
        if recent:
            return False
        db.insert("orch_gate_alarms", {
            "gate": ALARM_GATE,
            "kind": ALARM_KIND,
            "verdict": "blocked",
            "n": 1,
            "window_hours": hours,
            "detail": json.dumps({
                "task_id": task.get("id"),
                "slug": task.get("slug"),
                "artifact_commit": sha,
                "reason": reason,
            })[:2000],
        })
        return True
    except Exception as exc:
        print(f"[merge-truth] alarm write failed (non-fatal): {exc}")
        return False


def gate_merged_patch(task, patch, repo=None, prod_branch=None, fetch=True):
    """Vet a task patch before it is written. Returns the patch to apply, or None.

    None means "write nothing" — reserved for infra errors, where the honest action is to
    leave the row exactly as it is and try again next cycle.

    A patch that does not set MERGED passes through untouched, so callers can route every
    update through this without special-casing.
    """
    if str(patch.get("state") or "").upper() != "MERGED":
        return patch

    sha = (patch.get("artifact_commit") or task.get("artifact_commit") or "").strip()
    repo, prod_branch, err = resolve_target(task, repo, prod_branch)
    if err:
        print(f"[merge-truth] {task.get('slug')}: {err}; leaving state unchanged")
        return None

    verdict, reason = verify_merge_reachable(repo, sha, prod_branch, fetch=fetch)

    if verdict == OK:
        return patch

    if verdict == INFRA_ERROR:
        # Never downgrade on an infrastructure failure.
        print(f"[merge-truth] {task.get('slug')}: cannot verify ({reason}); "
              f"leaving state unchanged")
        return None

    blocked = dict(patch)
    blocked["state"] = PHANTOM_STATE
    prior = str(patch.get("note") or "").strip()
    blocked["note"] = (f"merge-truth: MERGED blocked — {reason} "
                       f"(prod_branch={prod_branch}, sha={sha[:12] or 'none'})"
                       + (f" | {prior}" if prior else ""))[:2000]
    raise_phantom_alarm(task, sha, reason)
    print(f"[merge-truth] {task.get('slug')}: BLOCKED MERGED -> {PHANTOM_STATE} ({reason})")
    return blocked


def guarded_task_update(task, patch, repo=None, prod_branch=None, fetch=True):
    """gate_merged_patch + db.update. Returns the applied patch, or None if nothing written."""
    final = gate_merged_patch(task, patch, repo=repo, prod_branch=prod_branch, fetch=fetch)
    if final is None:
        return None
    db.update("tasks", {"id": task["id"]}, final)
    return final


# ── read-only reconciler ─────────────────────────────────────────────────────

def reconcile(project=None, limit=500, fetch=True, since=None):
    """Report how many MERGED rows are actually reachable. Mutates nothing, by construction.

    Operators need to ask "how many of our merges are real?" without trusting the writer.
    """
    params = {
        "select": "id,slug,project_id,artifact_commit,updated_at",
        "state": "eq.MERGED",
        "order": "updated_at.desc",
        "limit": str(limit),
    }
    if since:
        params["updated_at"] = f"gte.{since}"
    try:
        tasks = db.select("tasks", params) or []
    except Exception as exc:
        return {"ok": False, "error": f"task query failed: {exc}"}

    projects = {}
    try:
        for row in db.select("projects", {
                "select": "id,name,repo_path,prod_branch,default_base"}) or []:
            projects[row["id"]] = row
    except Exception as exc:
        return {"ok": False, "error": f"project query failed: {exc}"}

    counts = {OK: 0, PHANTOM: 0, INFRA_ERROR: 0}
    per_project = {}
    offenders = []

    for t in tasks:
        row = projects.get(t.get("project_id")) or {}
        pname = row.get("name") or "?"
        if project and pname != project:
            continue
        repo = row.get("repo_path")
        prod = row.get("prod_branch") or row.get("default_base")
        verdict, reason = verify_merge_reachable(
            repo, t.get("artifact_commit"), prod, fetch=fetch)
        counts[verdict] += 1
        bucket = per_project.setdefault(pname, {OK: 0, PHANTOM: 0, INFRA_ERROR: 0})
        bucket[verdict] += 1
        if verdict == PHANTOM:
            offenders.append({"slug": t.get("slug"), "project": pname,
                              "artifact_commit": t.get("artifact_commit"),
                              "reason": reason})

    checked = sum(counts.values())
    verifiable = counts[OK] + counts[PHANTOM]
    return {
        "ok": True,
        "checked": checked,
        "real": counts[OK],
        "phantom": counts[PHANTOM],
        "unverifiable": counts[INFRA_ERROR],
        # Share is over what could actually be decided; infra errors are unknown, not bad.
        "real_share": round(counts[OK] / verifiable, 4) if verifiable else None,
        "per_project": per_project,
        "offenders": offenders[:50],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Report which MERGED tasks really reached prod.")
    ap.add_argument("--project", default=None)
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--since", default=None, help="ISO timestamp lower bound on updated_at")
    ap.add_argument("--no-fetch", action="store_true",
                    help="skip git fetch (faster; may report stale infra_error)")
    args = ap.parse_args(argv)
    report = reconcile(project=args.project, limit=args.limit,
                       fetch=not args.no_fetch, since=args.since)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
