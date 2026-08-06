#!/usr/bin/env python3
"""
deployment_terminal.py — makes DEPLOYMENT, not merge, the terminal state of a task.

WHY
---
`MERGED` was terminal. Nothing downstream checked whether the change ever reached a
user. The audit found `releases` at 2,714 failed / 90 success over 30 days (3.2%) —
`tomorrow` at 277 failed / 0 success — and *nothing changed as a result*. Production
only shipped at all because Vercel's git integration auto-deploys on push; the
orchestrator's own release path was ~97% dead and invisible.

WHAT THIS ADDS
--------------
1. A real terminal state `DEPLOYED_AND_VERIFIED`, reached only when BOTH hold:
      a) the project's production URL returns HTTP 200, AND
      b) the release commit SHA is actually live in the deployed build
         (Vercel's READY production deployment reports that exact SHA).
   Merge alone can no longer be mistaken for delivery.

2. Back-pressure: a project whose most recent release failed is BLOCKED — it stops
   accepting new work until a release goes green. Previously 2,714 failures produced
   no back-pressure at all.

3. The convergence gate: **nothing that cannot itself reach the terminal state may
   spawn children.** Decomposition/continuation must call `can_spawn_children()`
   first. This is what stops the ~10:1 fan-out amplification.

ENV FLAGS
---------
  ORCH_DEPLOY_TERMINAL_ENABLED   default ON  — promote verified tasks to DEPLOYED_AND_VERIFIED
  ORCH_RELEASE_BACKPRESSURE      default ON  — block new work for red projects
  ORCH_CONVERGENCE_GATE          default ON  — enforce the no-spawn-without-terminal rule
  ORCH_BACKPRESSURE_GRACE_MIN    default 45  — minutes a failed release may age before blocking
Set any to 0 to disable (they are safety rails, so they default ON, unlike the
self-work gates in self_work_gate.py).
"""
import os
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

DEPLOYED_AND_VERIFIED = "DEPLOYED_AND_VERIFIED"

# Release states that mean "this project is red and must not take new work".
FAILED_RELEASE_STATES = {"failed", "error", "rolled_back", "verification_blocked", "rollback_failed"}
GOOD_RELEASE_STATES = {"success", "deployed", DEPLOYED_AND_VERIFIED.lower()}

_TRUTHY = ("1", "true", "yes", "on")


def _on(flag, default="1"):
    return os.environ.get(flag, default).strip().lower() in _TRUTHY


def _grace_minutes():
    try:
        return int(os.environ.get("ORCH_BACKPRESSURE_GRACE_MIN", "45"))
    except Exception:
        return 45


# ---------------------------------------------------------------- verification


def _prod_url(project, project_row=None, health=None):
    """Best-effort production URL for a project."""
    row = project_row or {}
    if not row:
        try:
            row = (db.select("projects", {"select": "*", "name": f"eq.{project}"}) or [{}])[0]
        except Exception:
            row = {}
    h = health or {}
    if not h:
        try:
            h = (db.select("deploy_health", {"select": "*", "app": f"eq.{project}"}) or [{}])[0]
        except Exception:
            h = {}
    url = (h.get("prod_url") or h.get("url") or row.get("prod_url")
           or row.get("production_url") or row.get("url") or "")
    url = str(url or "").strip()
    if url and not url.startswith("http"):
        url = "https://" + url
    return url


def http_ok(url, timeout=20):
    """(status_code, ok) for a plain GET. A 200 is required — 3xx/4xx/5xx are not delivery."""
    if not url:
        return None, False
    req = urllib.request.Request(url, headers={"User-Agent": "beethoven-deploy-verify/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.status == 200
    except urllib.error.HTTPError as e:
        return e.code, False
    except Exception:
        return None, False


def sha_is_live(project, sha, vercel_project=None):
    """True only if Vercel's READY production deployment carries exactly this commit SHA.

    This is the 'the changed behavior is actually present' check at its minimum honest
    form: the build serving production was built from this commit, not merely 'a deploy
    happened around then'.
    """
    if not sha:
        return False, "no release sha"
    try:
        import deploy_verify
        vproj = vercel_project or deploy_verify._vercel_project(project)
        dep = deploy_verify._latest_deploy(vproj, sha=sha)
    except Exception as e:
        return False, f"vercel lookup failed: {e}"
    if not dep or dep.get("_auth_error"):
        return False, (dep or {}).get("_auth_error") or "no production deployment found"
    state = dep.get("state") or dep.get("readyState")
    if state not in ("READY",):
        return False, f"production deployment state={state}"
    meta = dep.get("meta") or {}
    live = str(meta.get("githubCommitSha") or "")
    if not live:
        return False, "deployment reports no commit sha"
    if live == str(sha) or live.startswith(str(sha)[:12]) or str(sha).startswith(live[:12]):
        return True, f"sha {live[:12]} live"
    return False, f"live sha {live[:12]} != release sha {str(sha)[:12]}"


def verify_release(release, project_row=None, health=None):
    """Full terminal check for one release row. Returns a dict; ok=True only if BOTH pass."""
    project = release.get("project")
    sha = release.get("to_sha")
    url = release.get("vercel_url") or _prod_url(project, project_row, health)
    if url and not url.startswith("http"):
        url = "https://" + url
    status, ok200 = http_ok(url)
    live, why = sha_is_live(project, sha)
    return {"project": project, "sha": sha, "url": url, "http_status": status,
            "http_ok": ok200, "sha_live": live, "sha_reason": why,
            "ok": bool(ok200 and live),
            "reason": ("verified" if (ok200 and live)
                       else f"http={status} sha_live={live} ({why})")}


# ------------------------------------------------------------------ promotion


def _commit_in_release(repo, artifact_commit, release_sha):
    """Per-task evidence check: True only when artifact_commit is non-empty and git
    confirms it is an ancestor of (or equal to) the verified release sha."""
    return _classify_candidate(repo, artifact_commit, release_sha) == "promotable"


# Promotion funnel buckets. Kept as constants so the log, the return value and the
# tests all name the same thing.
BUCKET_PROMOTABLE = "promotable"
BUCKET_NO_COMMIT = "skipped_no_commit"
BUCKET_NOT_ANCESTOR = "skipped_not_ancestor"
BUCKET_COMMIT_ABSENT = "skipped_commit_absent"


def _commit_exists(repo, sha):
    """True when the object is present in this repo."""
    try:
        r = subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"],
                           cwd=repo, capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def _classify_candidate(repo, artifact_commit, release_sha):
    """Say WHY a task is or is not promotable, not merely whether it is.

    The previous boolean collapsed three very different situations into False:
    no evidence recorded, evidence that predates//diverges from this release, and
    evidence naming a commit that never reached origin at all. Only the last is a
    lost-work signal, and flattening it is why a stranded-on-local-disk population
    stayed invisible. Callers need the distinction to route recovery.
    """
    sha = (artifact_commit or "").strip()
    if not sha:
        return BUCKET_NO_COMMIT
    if not release_sha or not repo or not os.path.isdir(repo):
        # Cannot evaluate evidence; treat as unproven rather than lost.
        return BUCKET_NOT_ANCESTOR
    if not _commit_exists(repo, sha):
        return BUCKET_COMMIT_ABSENT
    try:
        r = subprocess.run(["git", "merge-base", "--is-ancestor", sha, release_sha],
                           cwd=repo, capture_output=True, text=True, timeout=30)
        return BUCKET_PROMOTABLE if r.returncode == 0 else BUCKET_NOT_ANCESTOR
    except Exception:
        return BUCKET_NOT_ANCESTOR


def _select_all_merged_with_commit(pid, cutoff, page_size=None):
    """Every MERGED task for the project that HAS artifact_commit evidence.

    Server-side filter + deterministic order + pagination to exhaustion. The old
    query took an unordered LIMIT 500 out of 1,296 MERGED rows, of which only ~146
    even had an artifact_commit: the ~19 promotable ones could be missed entirely,
    and two runs could promote different sets. Filtering server-side shrinks the
    candidate set to the rows that could possibly qualify, so the window question
    disappears instead of moving to a bigger number.
    """
    try:
        page_size = int(page_size or os.environ.get("ORCH_PROMOTE_PAGE_SIZE", "500"))
    except (TypeError, ValueError):
        page_size = 500
    page_size = max(1, page_size)

    base = {"select": "id,slug,state,artifact_commit",
            "project_id": f"eq.{pid}",
            "state": "eq.MERGED",
            "artifact_commit": "not.is.null",
            "order": "id.asc"}
    if cutoff:
        base["updated_at"] = f"lte.{cutoff}"

    out, offset, seen = [], 0, set()
    while True:
        q = dict(base, limit=str(page_size), offset=str(offset))
        try:
            rows = db.select("tasks", q) or []
        except Exception:
            # Degrade to a single unfiltered page rather than promoting nothing at all.
            if offset == 0:
                try:
                    rows = db.select("tasks", {"select": "id,slug,state,artifact_commit",
                                               "project_id": f"eq.{pid}",
                                               "state": "eq.MERGED",
                                               "order": "id.asc",
                                               "limit": str(page_size)}) or []
                except Exception:
                    rows = []
                out.extend(rows)
            break
        for r in rows:
            rid = r.get("id")
            if rid not in seen:
                seen.add(rid)
                out.append(r)
        if len(rows) < page_size:
            break
        offset += page_size
        if offset > 100000:   # pathological guard; never silently truncate quietly
            print("deployment_terminal: promotion scan exceeded 100k rows — stopping")
            break
    return out


def _route_absent_commits_to_recovery(project, absent):
    """Hand the stranded-on-local-disk population to recovery instead of dropping it.

    These tasks name a commit that no longer exists anywhere we can see: real work
    that never reached origin. Fail-soft — recovery being unavailable must not stop
    a promotion pass that is otherwise correct.
    """
    if not absent:
        return 0
    try:
        import missing_branch_audit
        fn = getattr(missing_branch_audit, "auto_recover_missing_branches", None)
        if callable(fn):
            fn(dry_run=True, max_recover=len(absent))
    except Exception:
        pass
    for t in absent[:20]:
        print(f"deployment_terminal: RECOVERY-CANDIDATE {project} task={t.get('slug') or t.get('id')} "
              f"commit={(t.get('artifact_commit') or '')[:12]} — commit absent from repo, "
              f"work may exist only on another disk")
    return len(absent)


def promote_release(release, dry_run=False):
    """Promote a release's MERGED tasks to DEPLOYED_AND_VERIFIED once the release verifies.

    Only tasks that are currently MERGED for that project and were merged at or before
    the release are promoted; nothing is ever promoted on merge alone.
    """
    if not _on("ORCH_DEPLOY_TERMINAL_ENABLED"):
        return {"promoted": 0, "reason": "ORCH_DEPLOY_TERMINAL_ENABLED=0"}
    result = verify_release(release)
    if not result["ok"]:
        return {"promoted": 0, "reason": result["reason"], "verify": result}
    project = release.get("project")
    try:
        proj = (db.select("projects", {"select": "id,repo_path", "name": f"eq.{project}"}) or [{}])[0]
        pid = proj.get("id")
    except Exception:
        proj, pid = {}, None
    if not pid:
        return {"promoted": 0, "reason": "unknown project", "verify": result}
    repo = proj.get("repo_path") or ""
    try:
        repo = db.localize_repo_path(repo)
    except Exception:
        pass
    cutoff = release.get("deployed_at") or release.get("created_at")
    # SCAN-WINDOW FIX 2026-08-06: this used to take an UNORDERED `limit: 500` out of a
    # 1,296-row MERGED population, ~146 of which had any artifact_commit and ~19 of which
    # were actually promotable. The promotable rows could fall entirely outside the page,
    # so a verified green release promoted zero — and two runs could promote different
    # sets. Filter server-side to rows that carry evidence, order deterministically, and
    # page to exhaustion. Note the fix is NOT a bigger limit: that pattern has caused this
    # failure five times before here.
    tasks = _select_all_merged_with_commit(pid, cutoff)

    # TRUTH FIX 2026-08-04 (preserved): promotion once blanket-certified EVERY MERGED task
    # of a project whenever any release verified. Each task must carry an artifact_commit
    # that git confirms is an ancestor of the verified release sha. Tasks without that
    # evidence stay MERGED. The resulting number being low is the number being honest —
    # do not relax this to raise it.
    release_sha = str(result.get("sha") or "")
    buckets = {BUCKET_PROMOTABLE: [], BUCKET_NO_COMMIT: [],
               BUCKET_NOT_ANCESTOR: [], BUCKET_COMMIT_ABSENT: []}
    for t in tasks:
        buckets[_classify_candidate(repo, t.get("artifact_commit"), release_sha)].append(t)

    promotable = buckets[BUCKET_PROMOTABLE]
    funnel = {
        "candidates": len(tasks),
        BUCKET_NO_COMMIT: len(buckets[BUCKET_NO_COMMIT]),
        BUCKET_NOT_ANCESTOR: len(buckets[BUCKET_NOT_ANCESTOR]),
        BUCKET_COMMIT_ABSENT: len(buckets[BUCKET_COMMIT_ABSENT]),
    }

    def _log_funnel(promoted_n):
        # Emitted on EVERY run, including zero-promotion runs. A pass that promotes
        # nothing used to be indistinguishable from a pass that never ran, which is
        # the silence that hid the release deadlock for 17 days.
        print(f"deployment_terminal: promotion funnel for {project} @ {release_sha[:12]} — "
              f"candidates={funnel['candidates']} promoted={promoted_n} "
              f"skipped_no_commit={funnel[BUCKET_NO_COMMIT]} "
              f"skipped_not_ancestor={funnel[BUCKET_NOT_ANCESTOR]} "
              f"skipped_commit_absent={funnel[BUCKET_COMMIT_ABSENT]}")

    if dry_run:
        _log_funnel(0)
        return {"promoted": 0, "would_promote": len(promotable),
                "skipped_no_evidence": len(tasks) - len(promotable),
                "funnel": funnel, "verify": result, "dry_run": True}

    promoted = 0
    for t in promotable:
        try:
            db.update("tasks", {"id": t["id"]},
                      {"state": DEPLOYED_AND_VERIFIED,
                       "note": (f"deployment verified: {result['url']} @ {release_sha[:12]} "
                                f"(HTTP 200, sha live, contains {t['artifact_commit'][:12]})")})
            promoted += 1
        except Exception:
            pass

    # Commits we cannot find are not merely unproven — they are work that never reached
    # origin. Route them instead of dropping them on the floor.
    _route_absent_commits_to_recovery(project, buckets[BUCKET_COMMIT_ABSENT])

    _log_funnel(promoted)
    return {"promoted": promoted,
            "skipped_no_evidence": len(tasks) - len(promotable),
            "funnel": funnel, "verify": result}


# --------------------------------------------------------------- back-pressure


def blocking_release(project):
    """Return the failing release blocking `project`, or None if the project is green.

    A project is red when its MOST RECENT release is in a failed state and has aged past
    the grace window. That is real back-pressure: 2,714 failures used to change nothing.
    """
    if not project:
        return None
    try:
        rows = db.select("releases", {"select": "id,project,deploy_status,to_sha,created_at,note",
                                      "project": f"eq.{project}",
                                      "order": "created_at.desc", "limit": "1"}) or []
    except Exception:
        return None
    if not rows:
        return None
    rel = rows[0]
    status = str(rel.get("deploy_status") or "").strip().lower()
    if status not in FAILED_RELEASE_STATES:
        return None
    try:
        import deploy_verify
        if deploy_verify._age_minutes(rel) < _grace_minutes():
            return None            # still inside the grace window; a retry may fix it
    except Exception:
        pass
    return rel


def project_accepts_work(project, slug=""):
    """False when a project is red. Recovery/deploy-fix work is always allowed through —
    otherwise back-pressure would deadlock the very work that turns the project green."""
    if not _on("ORCH_RELEASE_BACKPRESSURE"):
        return True, "backpressure disabled"
    # HEALING EXEMPTIONS — these are the only slugs that can turn a red project green, so
    # they must always pass or back-pressure deadlocks the project forever. The prefixes are
    # taken from the slugs actually emitted in production:
    #   deployfix-<app>-<ts>  (deploy_verify._queue_deploy_fix)
    #   relfix-<app>-<sha>    (release train fix path)
    #   recover-missing-branch-*  (branch recovery)
    s = str(slug or "").lower()
    for allowed in ("deployfix", "deploy-fix", "relfix", "release-fix",
                    "rollback", "hotfix", "recover-missing-branch", "buildfix"):
        if allowed in s:
            return True, f"exempt ({allowed})"
    rel = blocking_release(project)
    if not rel:
        return True, "green"
    return False, (f"project '{project}' is RED: last release {str(rel.get('to_sha') or '')[:8]} "
                   f"is {rel.get('deploy_status')}; no new work until a release goes green "
                   f"(set ORCH_RELEASE_BACKPRESSURE=0 to override)")


# ------------------------------------------------------------ convergence gate


def can_spawn_children(task, reason_out=None):
    """THE CONVERGENCE GATE.

    Nothing that cannot itself reach the terminal state may spawn children. Every failure
    used to spawn tasks and nothing ever retired them (~10:1 amplification). A task may
    only fan out if it is itself still on a path to DEPLOYED_AND_VERIFIED.

    Blocked when the task is:
      * already in a dead/terminal-failure state (CLOSED/QUARANTINED/SHELVED/SUPERSEDED),
      * a shadow/non-integrating clone (structurally can never deploy),
      * owned by a project that is currently RED (its children could not deploy either).
    """
    if not _on("ORCH_CONVERGENCE_GATE"):
        return True, "convergence gate disabled"
    task = task or {}
    state = str(task.get("state") or "").upper()
    slug = str(task.get("slug") or "")

    # NOTE: BLOCKED is deliberately NOT in this list. A blocked task is not dead — decomposing
    # it is precisely how auto_remediate unblocks it, so gating BLOCKED would stall the very
    # remediation that lets work reach the terminal state. Only genuinely dead states qualify.
    if state in ("CLOSED", "QUARANTINED", "SHELVED", "SUPERSEDED"):
        return False, f"task {slug or task.get('id')} is {state} — cannot reach {DEPLOYED_AND_VERIFIED}, may not spawn children"
    if task.get("shadow_only"):
        return False, f"task {slug} is shadow_only — forbidden from integration, may not spawn children"
    if state == DEPLOYED_AND_VERIFIED:
        return False, f"task {slug} already reached {DEPLOYED_AND_VERIFIED} — nothing left to fan out"

    project = task.get("project") or _project_name(task.get("project_id"))
    ok, why = project_accepts_work(project, slug)
    if not ok:
        return False, f"convergence gate: {why}"
    return True, "ok"


def _project_name(project_id):
    if not project_id:
        return ""
    try:
        return (db.select("projects", {"select": "name", "id": f"eq.{project_id}"}) or [{}])[0].get("name") or ""
    except Exception:
        return ""


def gate_or_log(task, context=""):
    """Convenience wrapper: returns True if children may be spawned, logging refusals."""
    ok, why = can_spawn_children(task)
    if not ok:
        print(f"[convergence_gate] BLOCKED spawn{(' in ' + context) if context else ''}: {why}", flush=True)
    return ok


# ------------------------------------------------------------------------ job


def run():
    """Periodic pass: promote verified releases, report which projects are red."""
    rels = db.select("releases", {"select": "*", "deploy_status": "in.(success,deployed)",
                                  "order": "created_at.desc", "limit": "25"}) or []
    promoted = 0
    for rel in rels:
        try:
            promoted += promote_release(rel).get("promoted", 0)
        except Exception as e:
            print(f"deployment_terminal: promote failed for {rel.get('project')}: {e}")
    projects = [p["name"] for p in (db.select("projects", {"select": "name"}) or [])]
    red = []
    for name in projects:
        if blocking_release(name):
            red.append(name)
    print(f"deployment_terminal: promoted={promoted} red_projects={red or 'none'}")
    return {"promoted": promoted, "red_projects": red}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
