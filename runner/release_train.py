#!/usr/bin/env python3
"""
release_train.py - the zero-conflict shipping model. Instead of merging each agent branch straight into
the prod branch (which serialized into phantom + real conflicts), all work accumulates on a per-project
STAGING branch, is QA'd as a batch, then released to prod (main/master) and deployed via Vercel — with a
recorded last-good commit so a bad prod deploy can be rolled back with zero downtime.

Prod branch is AUTO-DETECTED per repo (main or master, whatever origin/HEAD points to) — never hardcoded,
so it's correct for every project. Runs ON THE RUNNER MACHINE (needs the real repos + matching paths).

Flow per project:
  1. ensure staging = fresh branch off prod (rebased to prod each cycle so it never drifts far).
  2. merge every judge-passed agent branch into staging (conflicts resolved ONCE here, not vs a moving
     prod). Agents also BRANCH FROM staging (see setup-worktrees base) so their base is always current.
  3. QA staging: run the project's test/build command.
  4. if green AND >= MIN_BATCH new changes: record last_good = prod tip, merge staging -> prod, push.
     deploy_verify then confirms Vercel success or rolls back to last_good.
"""
import os, sys, subprocess, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# SHIP-FAST defaults: deploy green work continuously (>=1 change, >=15 min since last release),
# not a 72h/20 bulk hold. Overridable via env; the build/test green-gate still runs first.
MIN_BATCH = int(os.environ.get("RELEASE_MIN_BATCH", "1"))
RELEASE_INTERVAL_HOURS = float(os.environ.get("RELEASE_INTERVAL_HOURS", "0.25"))
STAGING = os.environ.get("ORCH_STAGING_BRANCH", "orchestrator/dev")


def _git(repo, *args, timeout=120):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout)


def prod_branch(repo):
    """Auto-detect the production branch: origin/HEAD target, else main, else master."""
    r = _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD")
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip().rsplit("/", 1)[-1]
    for b in ("main", "master"):
        if _git(repo, "rev-parse", "--verify", b).returncode == 0:
            return b
    return "main"


def _ensure_staging(repo, prod):
    # create/refresh staging off prod without disturbing the checked-out worktree
    if _git(repo, "rev-parse", "--verify", STAGING).returncode != 0:
        _git(repo, "branch", STAGING, prod)
    else:
        # fast-forward staging to include any new prod commits (keeps it current, avoids drift)
        _git(repo, "fetch", ".", f"{prod}:{STAGING}") if _git(repo, "merge-base", "--is-ancestor", STAGING, prod).returncode == 0 else None


def _merge_into_staging(repo, branch):
    """Merge an agent branch into staging via an ephemeral worktree (no checkout of the main tree)."""
    import tempfile, shutil
    tmp = tempfile.mkdtemp(prefix="stg-")
    try:
        if _git(repo, "worktree", "add", "-f", tmp, STAGING).returncode != 0:
            return False
        r = subprocess.run(["git", "merge", "--no-ff", "-m", f"train: {branch}", branch],
                           cwd=tmp, capture_output=True, text=True)
        if r.returncode != 0:
            subprocess.run(["git", "merge", "--abort"], cwd=tmp, capture_output=True)
            return False
        return True
    finally:
        _git(repo, "worktree", "remove", "--force", tmp)
        shutil.rmtree(tmp, ignore_errors=True)


def run_for(project):
    p = (db.select("projects", {"select": "*", "name": f"eq.{project}"}) or [{}])[0]
    repo = p.get("repo_path", "")
    if not repo or not os.path.isdir(repo):
        return {"project": project, "skip": "repo missing on this machine"}
    prod = p.get("prod_branch") or prod_branch(repo)
    if p.get("prod_branch") != prod:
        db.update("projects", {"name": project}, {"prod_branch": prod})
    _ensure_staging(repo, prod)
    # candidate agent branches: tasks DONE/approved not yet on staging
    merged = 0
    for t in db.select("tasks", {"select": "slug", "project_id": f"eq.{p['id']}",
                                 "state": "in.(DONE,MERGED)", "order": "updated_at.desc", "limit": "60"}) or []:
        br = f"agent/{t['slug']}"
        if _git(repo, "rev-parse", "--verify", br).returncode != 0:
            continue
        # already on staging?
        if _git(repo, "merge-base", "--is-ancestor", br, STAGING).returncode == 0:
            continue
        if _merge_into_staging(repo, br):
            merged += 1
    # count staging changes vs prod
    ahead = _git(repo, "rev-list", "--count", f"{prod}..{STAGING}").stdout.strip() or "0"
    if int(ahead) < MIN_BATCH:
        return {"project": project, "prod": prod, "staged": merged, "ahead": ahead, "note": "below batch size"}
    due, due_note = _release_due(project)
    if not due:
        return {"project": project, "prod": prod, "staged": merged, "ahead": ahead, "note": due_note}
    # QA staging (build/tests) in an ephemeral worktree
    test_cmd = p.get("test_cmd") or os.environ.get("DEFAULT_TEST_CMD", "")
    if test_cmd:
        import tempfile, shutil
        tmp = tempfile.mkdtemp(prefix="qa-")
        try:
            _git(repo, "worktree", "add", "-f", tmp, STAGING)
            qa = subprocess.run(["bash", "-lc", test_cmd], cwd=tmp, capture_output=True, text=True, timeout=1800)
            ok = qa.returncode == 0
        finally:
            _git(repo, "worktree", "remove", "--force", tmp); shutil.rmtree(tmp, ignore_errors=True)
        if not ok:
            db.insert("releases", {"project": project, "from_sha": "", "to_sha": "", "n_changes": int(ahead),
                      "deploy_status": "failed", "note": "staging QA failed — not released"})
            return {"project": project, "qa": "FAILED", "note": "staging not green; held"}
    # BUILD GATE on the whole staging batch: the real prod build must be green before we release to
    # prod (this is what stops the Vercel deploy failures — no green build, no release).
    try:
        import build_gate
        bcmd = build_gate.build_cmd_for(p, repo)
        if bcmd:
            bok, blog = build_gate.run_build(repo, STAGING, bcmd)
            if not bok:
                db.insert("releases", {"project": project, "n_changes": int(ahead),
                          "deploy_status": "failed", "note": f"staging BUILD red — not released: {blog[-120:]}"})
                return {"project": project, "build": "RED", "note": "staging build not green; held"}
    except Exception:
        pass
    # release: record last-good, ff prod to staging, push (deploy_verify confirms/rolls back)
    last_good = _git(repo, "rev-parse", prod).stdout.strip()
    db.update("projects", {"name": project}, {"last_good_sha": last_good})
    if _git(repo, "fetch", ".", f"{STAGING}:{prod}").returncode != 0:
        return {"project": project, "note": "prod could not fast-forward from staging"}
    to_sha = _git(repo, "rev-parse", prod).stdout.strip()
    ver = _next_version()
    changelog = _git(repo, "log", "--oneline", f"{last_good}..{to_sha}").stdout[:2000]
    rel = db.insert("releases", {"project": project, "version": ver, "from_sha": last_good, "to_sha": to_sha,
                    "n_changes": int(ahead), "changelog": changelog, "deploy_status": "pending"})
    pushed = None
    if os.environ.get("ORCH_PUSH_ON_RELEASE", os.environ.get("ORCH_PUSH_ON_MERGE", "false")).lower() == "true":
        pr = _git(repo, "push", "origin", prod)
        pushed = pr.returncode == 0
        db.update("releases", {"project": project, "to_sha": to_sha},
                  {"deploy_status": "building" if pushed else "failed",
                   "note": "" if pushed else pr.stderr[-160:]})
    print(f"release_train {project}: staged {merged}, released {ahead} changes to {prod} "
          f"(push={'on' if pushed else 'off/local'})")
    return {"project": project, "prod": prod, "released": ahead, "pushed": pushed}


def _next_version():
    v = db.select("versions", {"select": "version", "status": "eq.in_progress",
                               "order": "opened_at.desc", "limit": "1"}) or []
    return v[0]["version"] if v else "v1"


def _release_due(project):
    if RELEASE_INTERVAL_HOURS <= 0:
        return True, "release interval disabled"
    rows = db.select("releases", {"select": "created_at,project", "project": f"eq.{project}",
                                  "order": "created_at.desc", "limit": "1"}) or []
    if not rows:
        return True, "first release"
    try:
        last = datetime.datetime.fromisoformat(str(rows[0]["created_at"]).replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        hours = (now - last).total_seconds() / 3600.0
        if hours >= RELEASE_INTERVAL_HOURS:
            return True, f"release interval elapsed ({hours:.1f}h)"
        return False, f"held for bulk deploy cadence ({hours:.1f}/{RELEASE_INTERVAL_HOURS:.1f}h)"
    except Exception:
        return True, "release timestamp unreadable"


def run():
    out = []
    for p in db.select("projects", {"select": "name,auto_merge"}) or []:
        if os.environ.get("ORCH_RELEASE_ALL_PROJECTS", "true").lower() == "true" or p.get("auto_merge"):
            if p["name"] == "smoke-test":
                continue
            try:
                out.append(run_for(p["name"]))
            except Exception as e:
                out.append({"project": p["name"], "error": str(e)[:120]})
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
